"""Call an external LLM to apply cache-optimization recommendations to a source file."""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import List

CLAUDE_MODELS = {
    "haiku":  "claude-haiku-4-5-20251001",
    "sonnet": "claude-sonnet-4-6",
    "opus":   "claude-opus-4-6",
}


def build_blind_prompt(source: str) -> str:
    return (
        "You are an expert C++ performance engineer.\n"
        "Fix any performance related issues with the code below.\n\n"
        "=== OUTPUT RULES ===\n"
        "- Output ONLY valid C++ code\n"
        "- Do NOT include markdown (no ```cpp)\n"
        "- Do NOT include explanations or summaries\n"
        "- Do NOT include comments about your changes\n"
        "- The output must compile as-is\n\n"
        "=== Instructions ===\n"
        "- Keep logic unchanged\n"
        "- Focus on cache performance, memory layout, and data access patterns\n\n"
        f"=== Code ===\n{source}\n"
    )


def build_prompt(source: str, recs: List[dict]) -> str:
    issues = []
    for i, r in enumerate(recs, 1):
        lines = r.get("lines") or []
        line_info = f"Lines: {', '.join(map(str, lines))}" if lines else "Lines: N/A"
        issues.append(
            f"Issue {i}:\n"
            f"Pattern: {r.get('pattern')}\n"
            f"Severity: {r.get('severity')}\n"
            f"{line_info}\n\n"
            f"Problem:\n{r.get('problem')}\n\n"
            f"Suggested Fix:\n{r.get('fix')}\n"
        )

    return (
        "You are an expert C++ performance engineer.\n"
        "Optimize the following code based on the cache optimization issues below.\n\n"
        "=== OUTPUT RULES ===\n"
        "- Output ONLY valid C++ code\n"
        "- Do NOT include markdown (no ```cpp)\n"
        "- Do NOT include explanations or summaries\n"
        "- Do NOT include comments about your changes\n"
        "- The output must compile as-is\n\n"
        "=== Instructions ===\n"
        "- Only modify code relevant to the issues\n"
        "- Keep logic unchanged\n\n"
        f"=== Issues ===\n{''.join(issues)}\n"
        f"=== Code ===\n{source}\n"
    )


def call_claude(prompt, api_key, model="sonnet", **_kwargs):
    import anthropic
    model_id = CLAUDE_MODELS.get(model, model)
    r = anthropic.Anthropic(api_key=api_key).messages.create(
        model=model_id,
        max_tokens=4096,
        temperature=0.2,
        messages=[{"role": "user", "content": prompt}],
    )
    return r.content[0].text


def call_chatgpt(prompt, api_key, **_kwargs):
    from openai import OpenAI
    r = OpenAI(api_key=api_key).chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "Output ONLY raw compilable C++ code. No explanations."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return r.choices[0].message.content


def call_gemini(prompt, api_key, **_kwargs):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    return genai.GenerativeModel("gemini-1.5-pro").generate_content(prompt).text


LLM_CALLERS = {"claude": call_claude, "chatgpt": call_chatgpt, "gemini": call_gemini}
LLM_ENV_VARS = {
    "claude": "ANTHROPIC_API_KEY",
    "chatgpt": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def clean_code(text: str) -> str:
    """Strip markdown fences if the LLM wrapped its output despite instructions."""
    out, in_fence = [], False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        out.append(line)
    return "\n".join(out).strip()


def _call_llm(llm, prompt, api_key, model=None):
    kwargs = {"model": model} if model else {}
    return clean_code(LLM_CALLERS[llm](prompt, api_key, **kwargs))


def apply_recommendations(source_path, recs, llm, api_key, model=None) -> str:
    source = Path(source_path).read_text()
    prompt = build_prompt(source, recs)
    return _call_llm(llm, prompt, api_key, model)


def apply_blind_fix(source_path, llm, api_key, model=None) -> str:
    source = Path(source_path).read_text()
    prompt = build_blind_prompt(source)
    return _call_llm(llm, prompt, api_key, model)


def optimized_path(source_path) -> str:
    p = Path(source_path)
    return str(p.with_name(p.stem + "_optimized" + p.suffix))


def mode_copy(source, recs, llm, api_key, out, model=None):
    code = apply_recommendations(source, recs, llm, api_key, model=model)
    dest = out or optimized_path(source)
    Path(dest).write_text(code)
    print(f"Optimized copy written to {dest}")


def mode_edit(source, recs, llm, api_key, model=None):
    code = apply_recommendations(source, recs, llm, api_key, model=model)
    Path(source).write_text(code)
    print("Original file updated")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("recommendations")
    ap.add_argument("source")
    ap.add_argument("--llm", choices=list(LLM_CALLERS), default="claude")
    ap.add_argument("--mode", choices=["edit", "copy"], default="copy")
    ap.add_argument("--api-key")
    ap.add_argument("--output", help="(copy mode) output path")
    args = ap.parse_args()

    recs = json.loads(Path(args.recommendations).read_text()).get("recommendations", [])
    if not recs:
        print("No recommendations found.")
        return

    env_var = LLM_ENV_VARS[args.llm]
    api_key = os.environ.get(env_var) or args.api_key
    if args.api_key:
        print("Warning: --api-key exposes the key in process listings; "
              f"prefer setting ${env_var} instead", file=sys.stderr)
    if not api_key:
        sys.exit(f"Error: no API key provided (set ${env_var})")

    if args.mode == "edit":
        mode_edit(args.source, recs, args.llm, api_key)
    else:
        mode_copy(args.source, recs, args.llm, api_key, args.output)


if __name__ == "__main__":
    main()
