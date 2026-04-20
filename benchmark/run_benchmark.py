#!/usr/bin/env python3
"""Benchmark harness: profile examples before/after fixes, store modular traces."""

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES_DIR = ROOT / "examples"
DATA_DIR = ROOT / "data"
TRACES_DIR = Path(__file__).resolve().parent / "traces"

EXAMPLES = [
    "aos_vs_soa",
    "column_major",
    "hot_cold",
    "pointer_chase",
    "random_access",
    "shared_variable",
    "comprehensive",
]

TIMING_RUNS = 3


def run_pipeline(source: Path) -> bool:
    r = subprocess.run(
        [sys.executable, str(ROOT / "run.py"), str(source), "--mode", "instruction"],
        cwd=ROOT,
    )
    return r.returncode == 0


def measure_runtime_ms(binary: Path, runs: int = TIMING_RUNS) -> float:
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        subprocess.run([str(binary)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elapsed = (time.perf_counter() - start) * 1000
        times.append(elapsed)
    return sum(times) / len(times)


def collect_traces(dest: Path, binary: Path):
    dest.mkdir(parents=True, exist_ok=True)

    artifacts = [
        (DATA_DIR / "results" / "variable_cache.json", dest / "variable_cache.json"),
        (DATA_DIR / "results" / "recommendations.json", dest / "recommendations.json"),
        (DATA_DIR / "results" / "perf_cache_lines.json", dest / "perf_cache_lines.json"),
        (DATA_DIR / "ast" / "ast_accesses.json", dest / "ast_accesses.json"),
    ]
    for src, dst in artifacts:
        if src.exists():
            shutil.copy2(src, dst)
        else:
            print(f"  Warning: {src.name} not found, skipping", file=sys.stderr)

    runtime = measure_runtime_ms(binary)
    (dest / "runtime_ms.txt").write_text(f"{runtime:.1f}\n")
    print(f"  Runtime: {runtime:.1f} ms (avg of {TIMING_RUNS} runs)")


def run_example(name: str, skip_fix: bool):
    source = EXAMPLES_DIR / f"{name}.cpp"
    fixed = EXAMPLES_DIR / f"{name}_fixed.cpp"
    binary = source.with_suffix("")
    fixed_binary = fixed.with_suffix("")
    trace_dir = TRACES_DIR / name

    if not source.exists():
        print(f"Skipping {name}: {source} not found", file=sys.stderr)
        return

    print(f"\n{'='*60}")
    print(f"Benchmarking: {name}")
    print(f"{'='*60}")

    print(f"\n--- Before (original) ---")
    if not run_pipeline(source):
        print(f"  Pipeline failed for {source.name}", file=sys.stderr)
        return
    collect_traces(trace_dir / "before", binary)

    if skip_fix:
        print(f"  Skipping 'after' phase (--skip-fix)")
        return

    if not fixed.exists():
        print(f"  No fixed file found at {fixed.name}, skipping 'after' phase")
        return

    print(f"\n--- After (fixed) ---")
    if not run_pipeline(fixed):
        print(f"  Pipeline failed for {fixed.name}", file=sys.stderr)
        return
    collect_traces(trace_dir / "after", fixed_binary)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--example", choices=EXAMPLES,
                    help="run a single example instead of all")
    ap.add_argument("--skip-fix", action="store_true",
                    help="only profile originals, skip fixed versions")
    args = ap.parse_args()

    targets = [args.example] if args.example else EXAMPLES

    for name in targets:
        run_example(name, args.skip_fix)

    has_after = any((TRACES_DIR / name / "after").exists() for name in targets)
    if has_after:
        print(f"\nRunning comparison...")
        subprocess.run([
            sys.executable,
            str(Path(__file__).resolve().parent / "compare.py"),
        ])
    else:
        print(f"\nNo 'after' traces found. Run without --skip-fix after creating fixed files.")

    print("\nDone.")


if __name__ == "__main__":
    main()
