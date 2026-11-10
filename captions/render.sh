#!/usr/bin/env bash
# One-command pipeline: transcribe -> build animated captions -> burn onto the video.
#
#   ./render.sh input.mp4                 # writes input_captioned.mp4
#   ./render.sh input.mp4 --accent "#6366F1" --uppercase   # extra flags go to build_captions.py
#
# Env overrides: MODEL=medium  PROMPT="Bioscriptz, biotech"  SKIP_TRANSCRIBE=1 (reuse existing words.json)
set -euo pipefail

IN="$1"; shift || true
HERE="$(cd "$(dirname "$0")" && pwd)"
BASE="${IN%.*}"
WORDS="${BASE}_words.json"
ASS="${BASE}_captions.ass"
OUT="${BASE}_captioned.mp4"

if [[ -z "${SKIP_TRANSCRIBE:-}" || ! -f "$WORDS" ]]; then
  python3 "$HERE/transcribe.py" "$IN" -o "$WORDS" --model "${MODEL:-small}" ${PROMPT:+--prompt "$PROMPT"}
fi

python3 "$HERE/build_captions.py" "$WORDS" --video "$IN" -o "$ASS" "$@"

# Burn captions on top. Resolution, frame rate, colour space and audio stay as in the source;
# only the pixels under the captions change. CRF 16 is visually lossless for H.264.
ffmpeg -y -hide_banner -i "$IN" \
  -vf "ass=filename='${ASS}':fontsdir='${HERE}/fonts'" \
  -map 0:v:0 -map 0:a? \
  -c:v libx264 -preset slow -crf 16 -pix_fmt yuv420p \
  -colorspace bt709 -color_primaries bt709 -color_trc bt709 \
  -c:a copy -movflags +faststart \
  "$OUT"

echo
echo "Done -> $OUT"
echo "Captions file (editable in Aegisub) -> $ASS"
