"""The provider-agnostic LLM interface.

Every LLM call in this project (item categorization, DM receipt structuring) is
single-turn, text-in / text-out — the DM adapter extracts the PDF's text layer
and asks the model to *structure* it, it never sends an image. So this is all
the interface needs to expose. Add a ``complete``-shaped method here and every
provider gets it for free.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """A minimal single-prompt text-completion backend."""

    #: short identifier, e.g. "ollama" / "openai" / "gemini"
    name: str = "base"

    @abstractmethod
    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        """Return the model's text response to a single user ``prompt``."""
        raise NotImplementedError

    def complete_vision(
        self,
        prompt: str,
        image_bytes: bytes,
        *,
        mime_type: str = "image/jpeg",
        temperature: float = 0.0,
    ) -> str:
        """Return the model's text response to a prompt + one image.

        Optional capability — providers without a vision model raise. Used for
        photographing arbitrary paper receipts.
        """
        raise NotImplementedError(f"The '{self.name}' provider does not support vision.")
