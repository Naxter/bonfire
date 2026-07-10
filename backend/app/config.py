"""Load environment configuration once, from the repo-root ``.env``.

The scrapers already call ``load_dotenv`` themselves; the backend historically
relied on the ambient process environment. Importing this module (done by the
LLM factory and every entrypoint) makes ``.env`` values available no matter how
the process was started — uvicorn, the watcher, or a one-shot script.
"""

from pathlib import Path

from dotenv import load_dotenv


def _find_dotenv() -> Path | None:
    """Walk up from this file until a ``.env`` is found (repo root)."""
    for parent in Path(__file__).resolve().parents:
        candidate = parent / ".env"
        if candidate.exists():
            return candidate
    return None


DOTENV_PATH = _find_dotenv()
if DOTENV_PATH:
    load_dotenv(DOTENV_PATH)
