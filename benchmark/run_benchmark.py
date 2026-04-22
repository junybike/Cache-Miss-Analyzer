#!/usr/bin/env python3
"""Benchmark harness: profile examples before/after fixes, store modular traces."""

import argparse
import subprocess
import sys
from pathlib import Path

from utils import ROOT, run_pipeline, collect_traces

EXAMPLES_DIR = ROOT / "examples"
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
    ap = argparse.ArgumentParser(
        description=__doc__,
        epilog="For grid benchmarks (model x condition), use grid_benchmark.py instead.",
    )
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
