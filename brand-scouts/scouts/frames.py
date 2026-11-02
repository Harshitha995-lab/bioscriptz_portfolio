"""Frames for the video hook and on-screen text hook. Needs ffmpeg on PATH and a direct https video URL.
Without them the analyst gets no images and reports those hooks as 'not analysed'."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .common import Reel

HOOK_SECONDS = (0.0, 1.0, 2.0, 3.0)   # the opening 3 seconds, where the hook lives
LATER_FRACTIONS = (0.35, 0.7)         # two later frames, to see the format and pacing
MAX_VIDEO_BYTES = 80_000_000


@dataclass
class Frames:
    times: list = field(default_factory=list)    # second of each image
    images: list = field(default_factory=list)   # JPEG bytes, same order


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def frame_times(duration_s: float | None) -> list[float]:
    times = [t for t in HOOK_SECONDS if duration_s is None or t < duration_s]
    if duration_s and duration_s > 6:
        times += sorted({round(duration_s * f, 1) for f in LATER_FRACTIONS if duration_s * f > 3.5})  # past the hook window
    return times


def extract_frames(video_path: Path, times: list[float], width: int = 512) -> Frames:
    out = Frames()
    for t in times:
        cmd = ["ffmpeg", "-v", "error", "-ss", str(t), "-i", str(video_path), "-frames:v", "1",
               "-vf", f"scale={width}:-2", "-f", "image2pipe", "-vcodec", "mjpeg", "-"]
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=60)
        except (subprocess.TimeoutExpired, OSError):
            continue
        if r.returncode == 0 and r.stdout:
            out.times.append(t)
            out.images.append(r.stdout)
    return out


def download(url: str, dest: Path, timeout: int = 60) -> None:
    if not url.startswith("https://"):
        raise ValueError("only https video URLs are fetched")
    size = 0
    with urllib.request.urlopen(url, timeout=timeout) as resp, open(dest, "wb") as fh:
        while chunk := resp.read(1 << 20):
            size += len(chunk)
            if size > MAX_VIDEO_BYTES:
                raise ValueError("video larger than the size limit")
            fh.write(chunk)


class FfmpegFrames:
    """Downloads a Reel's video and samples frames. Any failure returns no frames, never an error."""

    def frames_for(self, reel: Reel) -> Frames:
        if not reel.video_url or not ffmpeg_available():
            return Frames()
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "reel.mp4"
            try:
                download(reel.video_url, path)
            except Exception:
                return Frames()
            return extract_frames(path, frame_times(reel.duration_s))
