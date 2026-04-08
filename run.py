#!/usr/bin/env python3

import argparse, subprocess, sys, os
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

def run(cmd, cwd=None):
    res = subprocess.run(cmd, shell=True, cwd=cwd)
    if res.returncode != 0:
        sys.exit(res.returncode)

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument("source_file")
    parser.add_argument("--llm", default="claude")
    parser.add_argument("--mode", default="instruction")

    args = parser.parse_args()

    src = ROOT / args.source_file
    binary = src.with_suffix("")
    api_key = os.environ.get("ANTHROPIC_API_KEY")

    print("Building AST analyzer...")
    build_dir = ROOT / "analysis" / "build"
    run(f"mkdir -p {build_dir} && cmake -S {ROOT / 'analysis'} -B {build_dir} && make -C {build_dir}")

    print("Compiling source...")
    run(f"g++ -g -no-pie {src} -o {binary}")

    # print("Allowing perf permissions...")
    # run("sudo sysctl kernel.perf_event_paranoid=0")

    print("Running profiler pipeline...")
    run(f"./profiler/run_perf.sh {src} {binary} --llm {args.llm} --mode {args.mode} --api-key {api_key}", cwd=ROOT)

if __name__ == "__main__":
    main()