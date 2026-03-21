#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

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

AST_ANALYZER="$PROJECT_DIR/analysis/build/ast_analyzer"
if [ ! -x "$AST_ANALYZER" ]; then
    echo "Error: AST analyzer not built. Run: cd analysis && mkdir -p build && cd build && cmake .. && make"
    exit 1
fi

DATA_DIR="$PROJECT_DIR/data/perf"
RESULT_DIR="$PROJECT_DIR/data/results"
AST_DIR="$PROJECT_DIR/data/ast"

mkdir -p "$DATA_DIR" "$RESULT_DIR" "$AST_DIR"

# Clean up partial perf.data on failure
cleanup() {
    if [ $? -ne 0 ] && [ -f "$DATA_DIR/perf.data" ]; then
        rm -f "$DATA_DIR/perf.data"
        echo "Cleaned up partial perf.data"
    fi
}
trap cleanup EXIT

# -g enables call graphs so perf script outputs addresses on separate indented
# lines, which is the format parser.py expects.
echo "Recording perf data..."
perf record -e cache-misses:u -g -o "$DATA_DIR/perf.data" -- "$BINARY"

echo "Generating perf script..."
perf script -i "$DATA_DIR/perf.data" > "$DATA_DIR/perf_script.txt"

echo "Mapping addresses to source lines..."
python3 "$PROJECT_DIR/analysis/parser.py" "$BINARY" "$DATA_DIR/perf_script.txt" --source "$SOURCE" \
    > "$RESULT_DIR/perf_cache_lines.json"

echo "Running AST analyzer..."
GCC_INCLUDE=$(gcc -print-file-name=include 2>/dev/null)
"$AST_ANALYZER" "$SOURCE" -- -std=c++17 ${GCC_INCLUDE:+-isystem "$GCC_INCLUDE"} > "$AST_DIR/ast_accesses.json"

echo "Correlating data..."
python3 "$PROJECT_DIR/analysis/analyze.py" \
    "$AST_DIR/ast_accesses.json" \
    "$RESULT_DIR/perf_cache_lines.json" \
    > "$RESULT_DIR/variable_cache.json"

echo ""
echo "Generating recommendations..."
python3 "$PROJECT_DIR/analysis/recommend.py" \
    "$AST_DIR/ast_accesses.json" \
    "$RESULT_DIR/variable_cache.json" \
    "$RESULT_DIR/perf_cache_lines.json" \
    --json-output "$RESULT_DIR/recommendations.json" \
    | tee "$RESULT_DIR/recommendations.txt"
