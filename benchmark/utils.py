"""Shared benchmark utilities: pipeline invocation, timing, trace collection."""

import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"

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
