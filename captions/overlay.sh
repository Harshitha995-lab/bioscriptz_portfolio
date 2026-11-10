#!/usr/bin/env bash
# Render the animated captions as a TRANSPARENT ProRes 4444 clip for editing in
# DaVinci Resolve / Premiere / Final Cut. Put it on V2 above your untouched footage.
#
#   ./overlay.sh input.mp4                  # writes input_captions_overlay.mov + input_captions.srt
#   ./overlay.sh input.mp4 --accent "#6366F1"   # extra flags go to build_captions.py
#
# Env overrides: MODEL=medium  PROMPT="Bioscriptz, biotech"  SKIP_TRANSCRIBE=1 (reuse existing words.json)
set -euo pipefail

IN="$1"; shift || true
HERE="$(cd "$(dirname "$0")" && pwd)"
BASE="${IN%.*}"
WORDS="${BASE}_words.json"
ASS="${BASE}_captions.ass"
SRT="${BASE}_captions.srt"
OUT="${BASE}_captions_overlay.mov"

if [[ -z "${SKIP_TRANSCRIBE:-}" || ! -f "$WORDS" ]]; then
  python3 "$HERE/transcribe.py" "$IN" -o "$WORDS" --model "${MODEL:-small}" ${PROMPT:+--prompt "$PROMPT"}
fi

python3 "$HERE/build_captions.py" "$WORDS" --video "$IN" -o "$ASS" --srt "$SRT" "$@"

# Same size, frame rate and length as the source, fully transparent except the captions.
IFS=, read -r W H FPS < <(ffprobe -v error -select_streams v:0 \
  -show_entries stream=width,height,r_frame_rate -of csv=p=0 "$IN")
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$IN")

ffmpeg -y -hide_banner \
  -f lavfi -i "color=c=black@0.0:s=${W}x${H}:r=${FPS}:d=${DUR},format=yuva444p10le" \
  -vf "ass=filename='${ASS}':fontsdir='${HERE}/fonts':alpha=1" \
  -c:v prores_ks -profile:v 4444 -pix_fmt yuva444p10le -vendor apl0 \
  "$OUT"

echo
echo "Done -> $OUT  (transparent overlay, put on V2 in Resolve)"
echo "Plain subtitles -> $SRT  (optional: Resolve subtitle track / YouTube upload)"
