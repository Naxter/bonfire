"""Google Gemini backend — the other cloud option for the Raspberry Pi.

Uses the unified ``google-genai`` SDK (``from google import genai``).
"""

from __future__ import annotations

import os

from .base import LLMProvider


class GeminiProvider(LLMProvider):
    name = "gemini"

    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_PROVIDER=gemini but GEMINI_API_KEY is not set.")

        # Imported lazily so the package is only required when this provider is active.
        from google import genai

        self._genai = genai
        self._model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        self._client = genai.Client(api_key=api_key)

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        resp = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=self._genai.types.GenerateContentConfig(temperature=temperature),
        )
        return (resp.text or "").strip()

    def complete_vision(self, prompt, image_bytes, *, mime_type="image/jpeg", temperature=0.0):
        resp = self._client.models.generate_content(
            model=os.getenv("GEMINI_VISION_MODEL", self._model),
            contents=[
                self._genai.types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                prompt,
            ],
            config=self._genai.types.GenerateContentConfig(temperature=temperature),
        )
        return (resp.text or "").strip()
