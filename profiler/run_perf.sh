#!/bin/bash

set -e

BINARY=$1
NAME=$(basename $BINARY)

DATA_DIR="data/perf"
RESULT_DIR="data/results"

mkdir -p "$DATA_DIR"
mkdir -p "$RESULT_DIR"

echo "Recording perf data..."
# rm "$DATA_DIR/${NAME}.data"
perf record -e cache-misses:u -g -o "$DATA_DIR/${NAME}.data" -- "$BINARY"

echo "Generating perf script..."
perf script -i "$DATA_DIR/${NAME}.data" > "$DATA_DIR/${NAME}_script.txt"

echo "Running analysis..."
python3 analysis/parser.py "$BINARY" "$DATA_DIR/${NAME}_script.txt" \
    > "$RESULT_DIR/${NAME}_cache_lines.txt"

echo "[Parser.py]: Done."
echo "Results saved to $RESULT_DIR/${NAME}_cache_lines.txt"