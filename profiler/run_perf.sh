#!/bin/bash
# Record cache-miss samples, map addresses to source lines, run the AST
# analyzer, correlate, and emit recommendations.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
    echo "Usage: $0 <source.cpp> <binary> [--llm NAME] [--mode MODE] [--api-key KEY]" >&2
    exit 1
}

[[ $# -ge 2 ]] || usage

SOURCE=$1
BINARY=$2
shift 2

LLM="claude"
MODE="instruction"

while [[ $# -gt 0 ]]; do
    case $1 in
        --llm)     LLM="$2";     shift 2 ;;
        --mode)    MODE="$2";    shift 2 ;;
        --api-key) echo "Warning: --api-key is deprecated, use environment variables instead" >&2; shift 2 ;;
        *) echo "Unknown option: $1" >&2; exit 1 ;;
    esac
done

[[ -f "$SOURCE" ]] || { echo "Error: source file '$SOURCE' not found" >&2; exit 1; }
[[ -f "$BINARY" ]] || { echo "Error: binary '$BINARY' not found" >&2; exit 1; }

AST_ANALYZER="$PROJECT_DIR/analysis/build/ast_analyzer"
[[ -x "$AST_ANALYZER" ]] || {
    echo "Error: AST analyzer not built (run 'python3 run.py ...' from project root)" >&2
    exit 1
}

DATA_DIR="$PROJECT_DIR/data/perf"
RESULT_DIR="$PROJECT_DIR/data/results"
AST_DIR="$PROJECT_DIR/data/ast"
mkdir -p "$DATA_DIR" "$RESULT_DIR" "$AST_DIR"

# Remove partial perf.data if the pipeline aborts.
trap 'rc=$?; if [[ $rc -ne 0 && -f "$DATA_DIR/perf.data" ]]; then
    rm -f "$DATA_DIR/perf.data"
    echo "Cleaned up partial perf.data" >&2
fi' EXIT

# -g enables call graphs, which puts sample addresses on their own indented
# lines — the format parser.py expects.
echo "Recording perf data..."
perf record -e cache-misses:u -g -o "$DATA_DIR/perf.data" -- "$BINARY"

echo "Generating perf script..."
perf script -i "$DATA_DIR/perf.data" > "$DATA_DIR/perf_script.txt"

echo "Mapping addresses to source lines..."
python3 "$PROJECT_DIR/analysis/parser.py" "$BINARY" "$DATA_DIR/perf_script.txt" \
    --source "$SOURCE" > "$RESULT_DIR/perf_cache_lines.json"

echo "Running AST analyzer..."
GCC_INCLUDE=$(gcc -print-file-name=include 2>/dev/null || true)
"$AST_ANALYZER" "$SOURCE" -- -std=c++17 ${GCC_INCLUDE:+-isystem "$GCC_INCLUDE"} \
    > "$AST_DIR/ast_accesses.json"

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

if [[ "$MODE" != "instruction" ]]; then
    echo ""
    echo "Running LLM optimization..."
    python3 "$PROJECT_DIR/analysis/llm_integration.py" \
        "$RESULT_DIR/recommendations.json" \
        "$SOURCE" \
        --llm "$LLM" \
        --mode "$MODE"
fi
