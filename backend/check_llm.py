"""Verify the configured LLM actually works — run this after dropping in a key.

    python check_llm.py

Prints which provider/model resolved and does one tiny live completion, so you
know the API key is valid before the pipeline relies on it.
"""

import os
import sys

import app.config  # noqa: F401  (loads repo-root .env)
from app.llm import complete, get_provider, resolve_provider_name


def main() -> int:
    name = resolve_provider_name()
    print(f"Resolved provider: {name}")
    model = {
        "openai": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "gemini": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        "google": os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
    }.get(name, os.getenv("OLLAMA_MODEL", "gemma3:12b"))
    print(f"Model:             {model}")

    try:
        get_provider()  # constructs the client (checks the key is present)
    except Exception as e:
        print(f"❌ Provider not configured: {e}")
        return 1

    print("Sending a test prompt…")
    try:
        reply = complete("Reply with exactly one word: OK")
    except Exception as e:
        print(f"❌ Live call failed: {e}")
        return 1

    print(f"Response: {reply[:120]!r}")
    print("✅ LLM is reachable and responding." if reply.strip() else "⚠️ Empty response.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
