#!/bin/bash

set -e

if [ $# -lt 2 ]; then
    echo "Usage: $0 <source.cpp> <binary>"
    exit 1
fi

SOURCE=$1
BINARY=$2

if [ ! -f "$SOURCE" ]; then
    echo "Error: source file '$SOURCE' not found"
    exit 1
fi

if [ ! -f "$BINARY" ]; then
    echo "Error: binary '$BINARY' not found"
    exit 1
fi

DATA_DIR="data/perf"
RESULT_DIR="data/results"
AST_DIR="data/ast"

mkdir -p "$DATA_DIR" "$RESULT_DIR" "$AST_DIR"

echo "Recording perf data..."
perf record -e cache-misses:u -g -o "$DATA_DIR/perf.data" -- "$BINARY"

echo "Generating perf script..."
perf script -i "$DATA_DIR/perf.data" > "$DATA_DIR/perf_script.txt"

echo "Mapping addresses to source lines..."
python3 analysis/parser.py "$BINARY" "$DATA_DIR/perf_script.txt" --source "$SOURCE" \
    > "$RESULT_DIR/perf_cache_lines.json"

echo "Running AST analyzer..."
GCC_INCLUDE=$(gcc -print-file-name=include 2>/dev/null)
./analysis/build/ast_analyzer "$SOURCE" -- ${GCC_INCLUDE:+-isystem "$GCC_INCLUDE"} > "$AST_DIR/ast_accesses.json"

echo "Correlating data..."
python3 analysis/analyze.py \
    "$AST_DIR/ast_accesses.json" \
    "$RESULT_DIR/perf_cache_lines.json" \
    > "$RESULT_DIR/variable_cache.json"

echo ""
echo "Generating recommendations..."
python3 analysis/recommend.py \
    "$AST_DIR/ast_accesses.json" \
    "$RESULT_DIR/variable_cache.json" \
    "$RESULT_DIR/perf_cache_lines.json" \
    | tee "$RESULT_DIR/recommendations.txt"

python3 analysis/recommend.py \
    "$AST_DIR/ast_accesses.json" \
    "$RESULT_DIR/variable_cache.json" \
    "$RESULT_DIR/perf_cache_lines.json" \
    --json > "$RESULT_DIR/recommendations.json"
