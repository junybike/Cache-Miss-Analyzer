#!/usr/bin/env python3
"""Grid benchmark: profile baselines, generate LLM fixes, profile results.

Runs a full grid of (model x condition x example) experiments:
  - baseline:     original code, profiled once per example
  - blind:        LLM fixes without tool guidance
  - tool_guided:  LLM fixes using our tool's recommendations.json

Usage:
    python benchmark/grid_benchmark.py                        # full grid
    python benchmark/grid_benchmark.py --runs 3               # 3 runs per cell
    python benchmark/grid_benchmark.py --example hot_cold     # single example
    python benchmark/grid_benchmark.py --model sonnet         # single model
    python benchmark/grid_benchmark.py --condition blind      # single condition
    python benchmark/grid_benchmark.py --reuse-baselines      # skip re-profiling
    python benchmark/grid_benchmark.py --dry-run              # print plan only
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "analysis"))
from utils import ROOT, run_pipeline, collect_traces

EXAMPLES_DIR = ROOT / "examples"
TRACES_DIR = Path(__file__).resolve().parent / "traces"
RESULTS_DIR = Path(__file__).resolve().parent / "results"
LOG_FILE = Path(__file__).resolve().parent / "grid_log.json"

MODELS = ["haiku", "sonnet", "opus"]
CONDITIONS = ["blind", "tool_guided"]
EXAMPLES = [
    "aos_vs_soa",
    "column_major",
    "hot_cold",
    "pointer_chase",
    "random_access",
    "shared_variable",
    "comprehensive",
]

COMPILE_FLAGS = "-g -no-pie -O0"
LLM_RETRY_DELAY = 30


def log_event(event: dict):
    event["timestamp"] = datetime.now().isoformat()
    events = []
    if LOG_FILE.exists():
        try:
            events = json.loads(LOG_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    events.append(event)
    LOG_FILE.write_text(json.dumps(events, indent=2) + "\n")


def profile_baseline(name: str, run_id: int, reuse: bool) -> bool:
    trace_dir = TRACES_DIR / name / "baseline" / f"run_{run_id}"
    if reuse and (trace_dir / "variable_cache.json").exists():
        print(f"  Reusing existing baseline for {name} run {run_id}")
        return True

    source = EXAMPLES_DIR / f"{name}.cpp"
    binary = source.with_suffix("")
    if not source.exists():
        print(f"  Error: {source} not found", file=sys.stderr)
        return False

    print(f"  Profiling baseline (run {run_id})...")
    if not run_pipeline(source):
        print(f"  Pipeline failed for {source.name}", file=sys.stderr)
        log_event({"type": "baseline_failed", "example": name, "run": run_id})
        return False

    collect_traces(trace_dir, binary)
    log_event({"type": "baseline_done", "example": name, "run": run_id})
    return True


def generate_fix(name: str, model: str, condition: str, api_key: str, run_id: int = 1) -> Path:
    """Call the LLM to produce a fixed .cpp file. Returns path to the file."""
    from llm_integration import apply_blind_fix, apply_recommendations

    source = EXAMPLES_DIR / f"{name}.cpp"
    out_path = EXAMPLES_DIR / f"{name}_{condition}_{model}_run{run_id}.cpp"

    if condition == "blind":
        code = apply_blind_fix(str(source), "claude", api_key, model=model)
    else:
        recs_file = TRACES_DIR / name / "baseline" / "run_1" / "recommendations.json"
        if not recs_file.exists():
            raise FileNotFoundError(f"No recommendations for {name} — run baseline first")
        recs = json.loads(recs_file.read_text()).get("recommendations", [])
        if not recs:
            raise ValueError(f"Empty recommendations for {name}")
        code = apply_recommendations(str(source), recs, "claude", api_key, model=model)

    out_path.write_text(code + "\n")
    return out_path


def compile_fix(cpp_path: Path) -> tuple[bool, Path]:
    binary = cpp_path.with_suffix("")
    cmd = ["g++"] + shlex.split(COMPILE_FLAGS) + [str(cpp_path), "-o", str(binary)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  Compile failed: {r.stderr[:200]}", file=sys.stderr)
        return False, binary
    return True, binary


def record_failure(name: str, model: str, condition: str, reason: str, run_id: int = 1):
    trace_dir = TRACES_DIR / name / f"{condition}_{model}" / f"run_{run_id}"
    trace_dir.mkdir(parents=True, exist_ok=True)
    fail_data = {
        "status": "failed",
        "reason": reason,
        "timestamp": datetime.now().isoformat(),
    }
    (trace_dir / "FAILED.json").write_text(json.dumps(fail_data, indent=2) + "\n")
    log_event({"type": "cell_failed", "example": name, "model": model,
               "condition": condition, "run": run_id, "reason": reason})


def run_cell(name: str, model: str, condition: str, api_key: str, run_id: int = 1) -> bool:
    trace_dir = TRACES_DIR / name / f"{condition}_{model}" / f"run_{run_id}"

    print(f"  Generating {condition} fix with {model} (run {run_id})...")
    cpp_path = None
    for attempt in range(2):
        try:
            cpp_path = generate_fix(name, model, condition, api_key, run_id)
            break
        except Exception as e:
            if attempt == 0 and "429" in str(e):
                print(f"  Rate limited, retrying in {LLM_RETRY_DELAY}s...")
                time.sleep(LLM_RETRY_DELAY)
            else:
                print(f"  LLM error: {e}", file=sys.stderr)
                record_failure(name, model, condition, f"llm_error: {e}", run_id)
                return False

    if not cpp_path:
        record_failure(name, model, condition, "llm_error: exhausted retries", run_id)
        return False

    print(f"  Compiling {cpp_path.name}...")
    ok, binary = compile_fix(cpp_path)
    if not ok:
        record_failure(name, model, condition, "compile_error", run_id)
        return False

    print(f"  Profiling...")
    if not run_pipeline(cpp_path):
        print(f"  Pipeline failed for {cpp_path.name}", file=sys.stderr)
        record_failure(name, model, condition, "profile_error", run_id)
        return False

    collect_traces(trace_dir, binary)
    log_event({"type": "cell_done", "example": name, "model": model,
               "condition": condition, "run": run_id})
    return True


def plan_grid(examples, models, conditions, start_run=1, end_run=1):
    cells = []
    for run_id in range(start_run, end_run + 1):
        for name in examples:
            cells.append(("baseline", name, None, None, run_id))
            for model in models:
                for condition in conditions:
                    cells.append(("cell", name, model, condition, run_id))
    return cells


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--example", choices=EXAMPLES,
                    help="run a single example instead of all")
    ap.add_argument("--model", choices=MODELS,
                    help="run a single model instead of all")
    ap.add_argument("--condition", choices=CONDITIONS,
                    help="run a single condition instead of all")
    ap.add_argument("--runs", type=int, default=1,
                    help="number of runs per cell (default: 1)")
    ap.add_argument("--start-run", type=int, default=1,
                    help="first run ID (default: 1, use >1 to add runs to existing data)")
    ap.add_argument("--reuse-baselines", action="store_true",
                    help="skip re-profiling baselines if traces exist")
    ap.add_argument("--dry-run", action="store_true",
                    help="print planned actions without running")
    args = ap.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not args.dry_run and not api_key:
        sys.exit("Error: ANTHROPIC_API_KEY not set")

    examples = [args.example] if args.example else EXAMPLES
    models = [args.model] if args.model else MODELS
    conditions = [args.condition] if args.condition else CONDITIONS
    start_run = args.start_run
    end_run = args.start_run + args.runs - 1

    cells = plan_grid(examples, models, conditions, start_run, end_run)
    total = len(cells)

    if args.dry_run:
        num_runs = end_run - start_run + 1
        print(f"Grid plan: {len(examples)} examples x {len(models)} models x {len(conditions)} conditions x {num_runs} runs (run {start_run}-{end_run})")
        n_baselines = len(examples) * num_runs
        print(f"Total operations: {total} ({n_baselines} baselines + {total - n_baselines} LLM cells)\n")
        for i, (kind, name, model, condition, run_id) in enumerate(cells, 1):
            if kind == "baseline":
                tag = "SKIP" if args.reuse_baselines else "RUN"
                print(f"  [{i:2d}/{total}] [{tag}] baseline: {name} (run {run_id})")
            else:
                print(f"  [{i:2d}/{total}] [RUN] {name} / {condition} / {model} (run {run_id})")
        return

    successes = 0
    failures = 0
    start = time.time()

    for i, (kind, name, model, condition, run_id) in enumerate(cells, 1):
        if kind == "baseline":
            print(f"\n[{i}/{total}] Baseline: {name} (run {run_id})")
            ok = profile_baseline(name, run_id, args.reuse_baselines)
        else:
            print(f"\n[{i}/{total}] {name} / {condition} / {model} (run {run_id})")
            ok = run_cell(name, model, condition, api_key, run_id)

        if ok:
            successes += 1
        else:
            failures += 1

    elapsed = time.time() - start
    print(f"\n{'='*60}")
    print(f"Grid complete: {successes} succeeded, {failures} failed ({elapsed:.0f}s)")
    print(f"Traces in: {TRACES_DIR}")
    print(f"\nNext steps:")
    print(f"  python benchmark/compare.py --grid")
    print(f"  python benchmark/plot_results.py --grid")


if __name__ == "__main__":
    main()
