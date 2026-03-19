#!/bin/bash

set -e

BINARY=$1
SOURCE=$2
NAME=$(basename $BINARY)

DATA_DIR="data/perf"
RESULT_DIR="data/results"
AST_DIR="data/ast"

mkdir -p "$DATA_DIR"
mkdir -p "$RESULT_DIR"
mkdir -p "$AST_DIR"

echo "Recording perf data..."
# rm "$DATA_DIR/${NAME}.data"
perf record -e cache-misses:u -g -o "$DATA_DIR/perf.data" -- "$BINARY"

echo "Generating perf script..."
perf script -i "$DATA_DIR/perf.data" > "$DATA_DIR/perf_script.txt"

echo "Running analysis..."
python3 analysis/parser.py "$BINARY" "$DATA_DIR/perf_script.txt" \
    > "$RESULT_DIR/perf_cache_lines.txt"

echo "[Parser.py]: Done."
echo "Results saved to $RESULT_DIR/perf_cache_lines.txt"

./analysis/build/ast_analyzer "$SOURCE" -- > "$AST_DIR/ast_accesses.txt"

python3 analysis/analyze.py \
    "$AST_DIR/ast_accesses.txt" \
    "$RESULT_DIR/perf_cache_lines.txt" \
    > "$RESULT_DIR/variable_cache.txt"


