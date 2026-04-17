#!/usr/bin/env python3
"""End-to-end pipeline driver: build analyzer, compile source, profile, recommend."""

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()

LLM_PACKAGES = {
    "claude":  "anthropic",
    "chatgpt": "openai",
    "gemini":  "google-generativeai",
}

LLM_ENV_VARS = {
    "claude":  "ANTHROPIC_API_KEY",
    "chatgpt": "OPENAI_API_KEY",
    "gemini":  "GEMINI_API_KEY",
}


def ensure_llm_package(llm):
    pkg = LLM_PACKAGES.get(llm)
    if not pkg:
        return
    module = pkg.replace("-", "_").split(".")[0]
    try:
        __import__(module)
    except ImportError:
        print(f"Installing {pkg}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pkg, "-q"])


def run(cmd, cwd=None, env=None):
    print("$", " ".join(shlex.quote(c) for c in cmd), flush=True)
    r = subprocess.run(cmd, cwd=cwd, env=env)
    if r.returncode != 0:
        sys.exit(r.returncode)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source_file")
    ap.add_argument("--llm", default="claude", choices=list(LLM_PACKAGES))
    ap.add_argument("--mode", default="instruction",
                    choices=["instruction", "copy", "edit"])
    ap.add_argument("--cflags", default="-g -no-pie -O0",
                    help="flags passed to g++ (default: %(default)r)")
    args = ap.parse_args()

    src = ROOT / args.source_file
    binary = src.with_suffix("")
    env_var = LLM_ENV_VARS[args.llm]
    api_key = os.environ.get(env_var, "")

    if args.mode != "instruction":
        ensure_llm_package(args.llm)
        if not api_key:
            sys.exit(f"Error: {env_var} not set (required for --mode {args.mode})")

    if "-O0" not in args.cflags:
        print("Note: profiling a non-O0 build — aggressive inlining may make "
              "line-level attribution less accurate.", flush=True)

    build = ROOT / "analysis" / "build"
    build.mkdir(parents=True, exist_ok=True)

    print("Building AST analyzer...", flush=True)
    run(["cmake", "-S", str(ROOT / "analysis"), "-B", str(build)])
    run(["make", "-C", str(build)])

    print("Compiling source...", flush=True)
    run(["g++", *shlex.split(args.cflags), str(src), "-o", str(binary)])

    print("Running profiler pipeline...", flush=True)
    cmd = [str(ROOT / "profiler" / "run_perf.sh"), str(src), str(binary),
           "--llm", args.llm, "--mode", args.mode]
    env = os.environ.copy()
    if api_key:
        env[LLM_ENV_VARS[args.llm]] = api_key
    run(cmd, cwd=ROOT, env=env)


if __name__ == "__main__":
    main()
