"""Full transcripts for winning Reels. Used only for Reels where the scraper gave no transcript.

Needs ffmpeg and a speech-to-text engine. The default engine is faster-whisper (`pip install faster-whisper`),
which downloads a model on first use and runs on CPU. Nothing is kept: the video and audio live in a temporary
folder that is deleted afterwards.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from .common import Reel
from .frames import download, ffmpeg_available


class Transcriber(Protocol):
    def transcribe(self, audio_path: Path) -> str: ...


class FasterWhisperTranscriber:
    """Not exercised against the real library in this project's tests (it is not installed here)."""

    def __init__(self, model_size: str | None = None):
        from faster_whisper import WhisperModel  # lazy: only needed when transcripts are missing

        self.model = WhisperModel(model_size or os.environ.get("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")

    def transcribe(self, audio_path: Path) -> str:
        segments, _info = self.model.transcribe(str(audio_path), vad_filter=True)
        return " ".join(seg.text.strip() for seg in segments).strip()


class LazyTranscriber:
    """Builds the real engine on first use, so a model is only downloaded if a transcript is actually missing."""

    def __init__(self, factory):
        self._factory, self._engine = factory, None

    def transcribe(self, audio_path: Path) -> str:
        if self._engine is None:
            self._engine = self._factory()
        return self._engine.transcribe(audio_path)


def extract_audio(video_path: Path, wav_path: Path) -> bool:
    """16 kHz mono WAV, the format speech models expect. False if the video has no audio track."""
    cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(video_path), "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", str(wav_path)]
    try:
        r = subprocess.run(cmd, capture_output=True, timeout=120)
    except (subprocess.TimeoutExpired, OSError):
        return False
    return r.returncode == 0 and wav_path.exists() and wav_path.stat().st_size > 1000


def transcribe_file(video_path: Path, transcriber: Transcriber) -> str:
    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "audio.wav"
        if not extract_audio(video_path, wav):
            return ""
        return transcriber.transcribe(wav).strip()


def ensure_transcripts(reels: list[Reel], transcriber: Transcriber | None, max_reels: int = 150) -> dict:
    """Fill Reel.transcript where it is empty and a video URL exists. Never raises: failures are counted."""
    stats = {"already_had": 0, "transcribed": 0, "failed": 0, "skipped": 0, "reason": ""}
    todo = []
    for r in reels:
        if r.transcript:
            stats["already_had"] += 1
        elif r.video_url:
            todo.append(r)
        else:
            stats["skipped"] += 1
    if not todo:
        return stats
    if transcriber is None or not ffmpeg_available():
        stats["skipped"] += len(todo)
        stats["reason"] = "no transcriber or ffmpeg available"
        return stats
    for r in todo[:max_reels]:
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "reel.mp4"
            try:
                download(r.video_url, path)
                text = transcribe_file(path, transcriber)
            except Exception as exc:
                text = ""
                stats.setdefault("error", f"{type(exc).__name__}: {exc}")   # keep the first cause visible
        if text:
            r.transcript = text
            stats["transcribed"] += 1
        else:
            stats["failed"] += 1
    stats["skipped"] += max(len(todo) - max_reels, 0)
    return stats
