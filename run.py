#!/usr/bin/env python3

import argparse, subprocess, sys, os
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

LLM_PACKAGES = {
    "claude":  "anthropic",
    "chatgpt": "openai",
    "gemini":  "google-generativeai",
}

def ensure_llm_dependency(llm: str):
    package = LLM_PACKAGES.get(llm)
    if not package:
        return
    try:
        __import__(package.replace("-", "_").split(".")[0])
    except ImportError:
        print(f"Installing {package}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", package, "-q"])

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

    if args.mode != "instruction":
        ensure_llm_dependency(args.llm)
        if not api_key:
            print(f"Error: ANTHROPIC_API_KEY not set (required for --mode {args.mode})", flush=True)
            sys.exit(1)

    print("Building AST analyzer...", flush=True)
    build_dir = ROOT / "analysis" / "build"
    run(f"mkdir -p {build_dir} && cmake -S {ROOT / 'analysis'} -B {build_dir} && make -C {build_dir}")

    print("Compiling source...", flush=True)
    run(f"g++ -g -no-pie {src} -o {binary}")

    # print("Allowing perf permissions...")
    # run("sudo sysctl kernel.perf_event_paranoid=0")

    api_key_arg = f"--api-key {api_key}" if api_key else ""
    print("Running profiler pipeline...", flush=True)
    run(f"./profiler/run_perf.sh {src} {binary} --llm {args.llm} --mode {args.mode} {api_key_arg}", cwd=ROOT)

if __name__ == "__main__":
    main()