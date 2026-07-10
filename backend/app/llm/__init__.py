"""Pluggable LLM provider.

Pick the backend with the ``LLM_PROVIDER`` env var (``ollama`` | ``openai`` |
``gemini``) — or just drop in an ``OPENAI_API_KEY`` / ``GEMINI_API_KEY`` and it's
auto-detected. The rest of the codebase only calls ``complete()`` /
``complete_vision()`` and never imports a specific SDK. Same code on every
machine — a local Ollama on a dev box, a cloud API on the always-on Pi — the
only difference is ``.env``.

Cloud calls get a few automatic retries with backoff so a transient rate-limit
or network blip doesn't drop a receipt on the floor.
"""

from __future__ import annotations

import logging
import os
import time
from functools import cache

# Ensure repo-root .env is loaded before we read any provider config.
from .. import config  # noqa: F401
from .base import LLMProvider

logger = logging.getLogger(__name__)

_PROVIDERS = {
    "ollama": ("app.llm.ollama_provider", "OllamaProvider"),
    "openai": ("app.llm.openai_provider", "OpenAIProvider"),
    "gemini": ("app.llm.gemini_provider", "GeminiProvider"),
    "google": ("app.llm.gemini_provider", "GeminiProvider"),  # alias
}

_MAX_ATTEMPTS = int(os.getenv("LLM_MAX_RETRIES", "3"))


def resolve_provider_name() -> str:
    """The active provider: explicit ``LLM_PROVIDER`` wins; otherwise inferred
    from whichever API key is present (so pasting a key is enough)."""
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    if os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"):
        return "gemini"
    return "ollama"


@cache
def get_provider() -> LLMProvider:
    """Return the configured provider (constructed once, then cached)."""
    from importlib import import_module

    name = resolve_provider_name()
    try:
        module_path, class_name = _PROVIDERS[name]
    except KeyError:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{name}'. Use one of: "
            f"{', '.join(sorted(set(_PROVIDERS)))}."
        ) from None

    provider_cls = getattr(import_module(module_path), class_name)
    return provider_cls()


def _with_retry(fn):
    """Retry a provider call a few times with exponential backoff. Never retries
    NotImplementedError (a permanent 'no vision support')."""
    last_error = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            return fn()
        except NotImplementedError:
            raise
        except Exception as e:  # network / rate-limit / transient 5xx
            last_error = e
            if attempt < _MAX_ATTEMPTS:
                delay = min(2 ** (attempt - 1), 8)
                logger.warning("LLM call failed (attempt %s/%s): %s — retrying in %ss",
                               attempt, _MAX_ATTEMPTS, e, delay)
                time.sleep(delay)
    raise last_error


def complete(prompt: str, *, temperature: float = 0.0) -> str:
    """Send a single prompt to the configured LLM and return its text reply."""
    return _with_retry(lambda: get_provider().complete(prompt, temperature=temperature))


def complete_vision(prompt: str, image_bytes: bytes, *, mime_type: str = "image/jpeg",
                    temperature: float = 0.0) -> str:
    """Send a prompt + image to the configured LLM (requires a vision model)."""
    return _with_retry(
        lambda: get_provider().complete_vision(
            prompt, image_bytes, mime_type=mime_type, temperature=temperature
        )
    )
