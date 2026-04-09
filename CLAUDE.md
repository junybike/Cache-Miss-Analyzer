# Cache Miss Analyzer

## Running the Analyzer

To profile a C++ file and generate recommendations:
```
python3 run.py <source_file> --mode instruction
```

This runs the full pipeline (perf profiling → AST analysis → correlation → recommendations)
and writes structured output to `data/results/recommendations.json`.

## Modes

| Mode          | Description                                                        |
|---------------|--------------------------------------------------------------------|
| `instruction` | Print recommendations to stdout. No LLM needed.                    |
| `copy`        | Call an external LLM to write `<source>_optimized.cpp`.            |
| `edit`        | Call an external LLM to overwrite the original source in place.    |

The `--llm` flag (`claude`, `chatgpt`, `gemini`) is only relevant for `copy` and `edit` modes.

## Claude Code Workflow

**Do not use `--mode copy` or `--mode edit`.** You are already here — apply the fixes directly.

1. Run instruction mode to get recommendations and generate the JSON:
   ```
   python3 run.py <source_file> --mode instruction
   ```
2. Read `data/results/recommendations.json` for the structured recommendation data.
3. Read the source file and apply every recommendation, writing the result to `<source>_fixed.cpp`.
4. Verify by re-running instruction mode on the fixed file and confirming miss counts drop.

## Data Files

After a run, intermediate data is written to:

| File                                  | Contents                              |
|---------------------------------------|---------------------------------------|
| `data/results/recommendations.json`  | Structured recommendations (use this) |
| `data/results/variable_cache.json`   | Per-variable cache miss counts        |
| `data/ast/ast_accesses.json`         | AST variable access info              |
| `data/perf/perf_script.txt`          | Raw perf output                       |
