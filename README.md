# Cache Miss Analyzer

Identifies which C++ variables cause the most CPU cache misses by combining Clang AST static analysis with Linux `perf` hardware profiling, then generates optimization recommendations.

## How It Works

```
perf record ──► parser.py ──► ast_analyzer ──► analyze.py ──► recommend.py
 (samples)    (addr→line)    (AST→JSON)     (correlate)    (pattern match)
```

Each stage reads and writes JSON. Human-readable output goes to stderr or tee'd files; structured JSON goes to stdout.

## Dependencies

**Debian/Ubuntu:**

```bash
sudo apt install linux-perf libclang-19-dev zlib1g-dev libzstd-dev cmake g++ python3 binutils
```

**Fedora/RHEL:**

```bash
sudo dnf install perf clang-devel llvm-devel zlib-devel libzstd-devel cmake gcc-c++ python3 binutils
```

## Quick Start

```bash
# 1. Build the AST analyzer
cd analysis && mkdir -p build && cd build && cmake .. && make && cd ../..

# 2. Compile an example (requires -g for debug symbols, -no-pie for reliable address mapping)
g++ -g -no-pie examples/comprehensive.cpp -o examples/comprehensive

# 3. Allow perf to profile your process
sudo sysctl kernel.perf_event_paranoid=0

# 4. Run the full pipeline (source first, binary second)
./profiler/run_perf.sh examples/comprehensive.cpp examples/comprehensive
```

## Output

| File | Contents |
|------|----------|
| `data/ast/ast_accesses.json` | Variable accesses, struct layouts, loop and pointer-advance metadata |
| `data/results/perf_cache_lines.json` | Cache miss counts per source line |
| `data/results/variable_cache.json` | Aggregated misses per variable with struct context |
| `data/results/recommendations.txt` | Human-readable optimization recommendations |
| `data/results/recommendations.json` | Machine-readable recommendations |

## Recommendation Rules

| Rule | Severity | Detects |
|------|----------|---------|
| Pointer chasing | HIGH | Linked-list traversal (`p = p->next`) in loops |
| Strided access | HIGH | Column-major traversal of row-major arrays |
| Random access | HIGH | Indirect array access (`arr[indices[i]]`) in loops |
| AoS to SoA | MEDIUM | Arrays of structs where most fields go unused in hot loops |
| Hot/cold partition | MEDIUM | Large structs (>128 bytes) where hot fields fit in one cache line but cold fields dominate |
| Struct reorder | LOW | Hot fields separated by cold fields across cache line boundaries |

## Running Individual Components

```bash
# AST analyzer alone
./analysis/build/ast_analyzer examples/comprehensive.cpp --

# Address-to-line mapping (--source improves filtering when binary and source names differ)
python3 analysis/parser.py examples/comprehensive data/perf/perf_script.txt --source examples/comprehensive.cpp

# Correlation
python3 analysis/analyze.py data/ast/ast_accesses.json data/results/perf_cache_lines.json

# Recommendations (text or JSON)
python3 analysis/recommend.py data/ast/ast_accesses.json data/results/variable_cache.json data/results/perf_cache_lines.json
python3 analysis/recommend.py data/ast/ast_accesses.json data/results/variable_cache.json data/results/perf_cache_lines.json --json
```

## Examples

| File | Target pattern |
|------|---------------|
| `examples/comprehensive.cpp` | All six rules in one file (primary integration test) |
| `examples/pointer_chase.cpp` | Pointer chasing |
| `examples/column_major.cpp` | Strided access |
| `examples/random_access.cpp` | Random / indirect access |
| `examples/aos_vs_soa.cpp` | AoS to SoA |
| `examples/hot_cold.cpp` | Hot/cold partition |

Compile any example with `g++ -g -no-pie`.

## Project Structure

```
479_project/
├── analysis/
│   ├── CMakeLists.txt
│   ├── ast_analyzer.cpp     Clang AST visitor → struct layouts + variable accesses
│   ├── parser.py             perf addresses → source line numbers
│   ├── analyze.py            correlate AST accesses with perf miss counts
│   └── recommend.py          pattern-matching rules → recommendations
├── examples/
│   ├── comprehensive.cpp     exercises all six detection patterns
│   ├── pointer_chase.cpp
│   ├── aos_vs_soa.cpp
│   ├── hot_cold.cpp
│   ├── column_major.cpp
│   └── random_access.cpp
├── profiler/
│   └── run_perf.sh           orchestrator script
└── data/
    ├── ast/                  AST analyzer output
    ├── perf/                 raw perf data
    └── results/              final output (variable cache, recommendations)
```

## Platform Support

This tool requires Linux `perf` for hardware cache-miss profiling. The full pipeline is Linux-only. On other platforms, only the static analysis component (`ast_analyzer`) can run natively.
