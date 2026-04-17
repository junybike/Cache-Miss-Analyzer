# Cache Miss Analyzer

Identifies which C++ variables cause the most CPU cache misses by combining Clang AST static analysis with Linux `perf` hardware profiling, then generates optimization recommendations.

## How It Works

```
perf record ──► parser.py ──────┐
 (samples)    (addr→line)       ├──► analyze.py ──► recommend.py   ──►   llm_integration.py
source.cpp ──► ast_analyzer ────┘   (correlate)    (pattern match)       (optional: LLM edit)
               (AST→JSON)
```

`parser.py` and `ast_analyzer` run independently — one maps perf samples to source lines, the other extracts struct layouts and access patterns. `analyze.py` correlates them, and `recommend.py` pattern-matches the result into advice. Each stage reads and writes JSON. `llm_integration.py` optionally hands the recommendations and source to an LLM to apply the fixes.

## Dependencies

**Debian/Ubuntu:**

```bash
sudo apt install linux-perf libclang-19-dev zlib1g-dev libzstd-dev cmake g++ python3 binutils
```

**Fedora/RHEL:**

```bash
sudo dnf install perf clang-devel llvm-devel zlib-devel libzstd-devel cmake gcc-c++ python3 binutils
```

Allow `perf` to profile without root:

```bash
sudo sysctl kernel.perf_event_paranoid=0
```

## Quick Start

```bash
# Run the full pipeline — builds the analyzer, compiles the source, profiles, recommends.
python3 run.py examples/comprehensive.cpp --mode instruction
```

Modes:

| Mode          | Behavior                                                                       |
|---------------|--------------------------------------------------------------------------------|
| `instruction` | Print recommendations. No LLM required.                                        |
| `copy`        | Call an LLM to produce `<source>_optimized.cpp` alongside the original.        |
| `edit`        | Call an LLM to overwrite the source in place.                                  |

Pick the LLM with `--llm {claude,chatgpt,gemini}`. `copy` and `edit` read the API key from the matching env var (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, or `GEMINI_API_KEY`).

`--cflags` overrides the compile flags (default `-g -no-pie -O0`). `-g` and `-no-pie` are required for reliable line-level attribution; higher optimization levels may reduce accuracy via inlining.

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
| Hot/cold partition | MEDIUM | Structs spanning >1 cache line where hot fields fit in one line but cold fields dominate |
| Struct reorder | LOW | Hot fields separated by cold fields across cache line boundaries |

Each rule lives in its own module under `analysis/rules/`. To add one, drop a `mymod.py` with a `run(ctx)` generator into that directory and register it in `rules/__init__.py`.

## Tuning

`recommend.py` uses an adaptive miss threshold: a variable is flagged only when its misses exceed **both** an absolute floor (50 samples) and 2% of total misses. This prevents a single dominant hot variable from masking other issues. Override with `--miss-threshold <N>`. Override the detected cache line size with `--cache-line <bytes>`.

## Running Individual Components

```bash
# AST analyzer
./analysis/build/ast_analyzer examples/comprehensive.cpp --

# Address → line mapping
python3 analysis/parser.py examples/comprehensive data/perf/perf_script.txt \
    --source examples/comprehensive.cpp

# Correlation
python3 analysis/analyze.py data/ast/ast_accesses.json data/results/perf_cache_lines.json

# Recommendations (text or JSON)
python3 analysis/recommend.py data/ast/ast_accesses.json \
    data/results/variable_cache.json data/results/perf_cache_lines.json [--json]

# LLM fix-up
python3 analysis/llm_integration.py data/results/recommendations.json \
    examples/comprehensive.cpp --llm claude --mode edit
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

## Project Structure

```
479_project/
├── run.py                        end-to-end driver (build, compile, profile, recommend)
├── analysis/
│   ├── CMakeLists.txt
│   ├── ast_analyzer.cpp          Clang AST visitor → struct layouts + variable accesses
│   ├── parser.py                 perf addresses → source line numbers
│   ├── analyze.py                correlate AST accesses with perf miss counts
│   ├── recommend.py              orchestrator: load JSON, run rules, emit recommendations
│   ├── llm_integration.py        hand code + recommendations to an LLM
│   └── rules/                    one file per recommendation rule
│       ├── common.py             tunables, helpers, context builders
│       ├── pointer_chasing.py
│       ├── aos_to_soa.py
│       ├── struct_reorder.py
│       ├── hot_cold_partition.py
│       ├── strided_access.py
│       └── random_access.py
├── examples/                     sample programs, one per pattern
├── profiler/
│   └── run_perf.sh               shell pipeline invoked by run.py
└── data/
    ├── ast/                      AST analyzer output
    ├── perf/                     raw perf data
    └── results/                  final output (variable cache, recommendations)
```

## Platform Support

Requires Linux `perf` for hardware cache-miss profiling. The full pipeline is Linux-only. On other platforms, only the static analysis component (`ast_analyzer`) can run natively.
