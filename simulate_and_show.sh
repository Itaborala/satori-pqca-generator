#!/usr/bin/env bash
#
# Run the synchronous (Aer) generator, visualize the newest dataset it wrote,
# and open the result.
#
#   ./run_and_show.sh                 # uses ex0.json
#   ./run_and_show.sh myrule.json     # a different Aer config
#   ./run_and_show.sh myrule.json 3   # ... at 3 fps (slower GIF)
#
# OUTDIR must match the generator's OUT_DIR.

set -eu

CONFIG="${1:-ex0.json}"
FPS="${2:-}"
OUTDIR="data-candidates"

echo ">> run: $CONFIG"
python generate-pqca-dataset.py run --config "$CONFIG"

# newest dataset, excluding manifests
DATASET=$(ls -t "$OUTDIR"/*.json 2>/dev/null | grep -v '\.manifest\.json$' | head -n1 || true)
[ -n "${DATASET:-}" ] || { echo "no dataset found in $OUTDIR/"; exit 1; }
echo ">> dataset: $DATASET"

# visualize; capture the path it prints ("wrote <path>")
if [ -n "$FPS" ]; then
    OUT=$(python visualize.py "$DATASET" --fps "$FPS" | sed -n 's/^wrote //p')
else
    OUT=$(python visualize.py "$DATASET" | sed -n 's/^wrote //p')
fi
[ -n "${OUT:-}" ] || { echo "visualize.py wrote nothing"; exit 1; }
echo ">> visual: $OUT"

# open it (Linux: xdg-open, macOS: open)
if command -v xdg-open >/dev/null 2>&1; then
    xdg-open "$OUT" >/dev/null 2>&1 &
elif command -v open >/dev/null 2>&1; then
    open "$OUT"
else
    echo ">> open manually: $OUT"
fi
