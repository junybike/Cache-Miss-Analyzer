# Cache Miss Analyzer

## How to run the cache miss analyzer
When asked to analyze a C++ file, run:
   python3 run.py <source_file> --llm claude --mode instruction

Available modes: 
- instruction: prints recommendations (default)
- copy: writes an *_optimized.cpp file
- edit: overwrites the original

For LLM option, use claude. 