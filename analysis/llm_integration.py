import json, argparse, os
from typing import List



# Builds the prompt which will get forwarded to an llm
def build_prompt(source_code: str, recs: List[dict]) -> str:
    text = ""
    
    for i, rec in enumerate(recs, 1):
        lines = rec.get("lines", [])
        info = f"Lines: {', '.join(map(str, lines))}" if lines else "Lines: N/A"

        text += f"""
Issue {i}:
Pattern: {rec.get("pattern")}
Severity: {rec.get("severity")}
{info}

Problem:
{rec.get("problem")}

Suggested Fix:
{rec.get("fix")}
"""
    
    return f"""
You are an expert C++ performance engineer.
Optimize the following code based on a cache optimization issue.


=== OUTPUT RULES ===
- Output ONLY valid C++ code
- Do NOT include markdown (no ```cpp)
- Do NOT include explanations
- Do NOT include comments about changes
- Do NOT include summaries
- The output must compile as-is

=== Instructions ===
- Only modify code relevant to the issues
- Keep logic unchanged

=== Issues ===
{text}

=== Code ===
{source_code}
""" 


# Makes call (LLM: chatgpt)
def chatgpt(prompt: str, api_key: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model="gpt-4.1",
        messages=[
            {"role": "system", "content": "Please output ONLY raw compilable C++ code. No explanations."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2,
    )
    return response.choices[0].message.content


# Makes call (LLM: claude)
def claude(prompt: str, api_key: str) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=4096,
        temperature=0.2,
        messages=[
            {"role": "user", "content": prompt}
        ]
    )
    return response.content[0].text


# Makes call (LLM: gemini)
def gemini(prompt: str, api_key: str) -> str:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel("gemini-1.5-pro")
    response = model.generate_content(prompt)
    return response.text


# Calls the LLM with a prompt and retrieves the code.
def call_llm(llm: str, prompt: str, api_key: str) -> str:
    if llm == "chatgpt":
        return chatgpt(prompt, api_key)
    elif llm == "claude":
        return claude(prompt, api_key)
    elif llm == "gemini":
        return gemini(prompt, api_key)
    else:
        raise ValueError(f"Unknown LLM: {llm}")


# Removes summaries and potential parts that are not in the generated code block by an LLM
def clean_code(text: str) -> str:
    lines = text.splitlines()
    cleaned = []
    in_code_block = False

    for line in lines:
        if line.strip().startswith("```"):
            in_code_block = not in_code_block
            continue
    
        if line.strip().lower().startswith(("summary", "**summary", "changes:", "- **")):
            break
        
        cleaned.append(line)
    
    return "\n".join(cleaned).strip()


# Gets prompt and forward it to the LLM. Retrieves the code.
def apply_recommendations(source_path: str, recs: List[dict], llm: str, api_key: str) -> str:
    with open(source_path) as f:
        code = f.read()
    
    prompt = build_prompt(code, recs)

    try:
        updated_code = call_llm(llm, prompt, api_key)
    except Exception as e:
        if "401" in str(e):
            print("LLM Error: Invalid API key")
        elif "429" in str(e):
            print("LLM Error: Exceeded current quota. Please check billing details.")
        else:
            print(f"LLM Error: {e}")
        exit(1)

    updated_code = clean_code(updated_code)
    return updated_code


# Output mode: print instruction
def mode_instruction(recs: List[dict]):
    print("=== Optimization Instructions ===\n")
    for rec in recs:
        print(f"[{rec['severity']}] {rec['pattern']}")
        print(f"Problem: {rec['problem']}")
        print(f"Fix: {rec['fix']}")
        print()


# Output mode: generate a copy
def mode_copy(source_path: str, recs: List[dict], llm: str, api_key: str, output_path: str = None):
    new_code = apply_recommendations(source_path, recs, llm, api_key)
    new_path = output_path or source_path.replace(".cpp", "_optimized.cpp")

    with open(new_path, "w") as file:
        file.write(new_code)

    print(f"Optimized copy written to {new_path}")


# Output mode: apply the recommendation on the original code
def mode_edit(source_path: str, recs: List[dict], llm: str, api_key: str):
    code = apply_recommendations(source_path, recs, llm, api_key)
    
    with open(source_path, "w") as file:
        file.write(code)

    print(f"Original file updated")


def main():
    parser = argparse.ArgumentParser(description="LLM based code optimizer")

    parser.add_argument("recommendations", help="recommendations.json")
    parser.add_argument("source", help="source code file")

    parser.add_argument("--llm", choices=["claude", "chatgpt", "gemini"], default="claude")
    parser.add_argument("--mode", choices=["instruction", "edit", "copy"], default="instruction")
    parser.add_argument("--api-key", help="API key for the selected LLM")
    parser.add_argument("--output", help="Output path for copy mode (default: <source>_optimized.cpp)")

    args = parser.parse_args()

    with open(args.recommendations) as file:
        data = json.load(file)
    
    recs = data.get("recommendations", [])

    if not recs:
        print("No recommendations found.")
        return
    
    api_key = args.api_key or os.environ.get("ANTHROPIC_API_KEY")

    if args.mode == "instruction":
        mode_instruction(recs)
        return

    if not api_key:
        print("Error: no API key provided")
        exit(1)

    if args.mode == "edit":
        mode_edit(args.source, recs, args.llm, api_key)
    elif args.mode == "copy":
        mode_copy(args.source, recs, args.llm, api_key, args.output)

if __name__ == "__main__":
    main()