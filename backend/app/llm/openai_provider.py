"""OpenAI backend — the recommended choice for the Raspberry Pi (no local GPU)."""

from __future__ import annotations

import os

from .base import LLMProvider


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self) -> None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("LLM_PROVIDER=openai but OPENAI_API_KEY is not set.")

        # Imported lazily so the package is only required when this provider is active.
        from openai import OpenAI

        self._model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        self._client = OpenAI(api_key=api_key)
        self._supports_temperature = True

    def _create(self, **kwargs):
        """chat.completions.create, dropping ``temperature`` for models that
        only accept the default (gpt-5*, o*) — learned from the first 400
        rather than maintained as a model-name list."""
        if not self._supports_temperature:
            kwargs.pop("temperature", None)
        try:
            return self._client.chat.completions.create(**kwargs)
        except Exception as e:
            msg = str(e)
            if "temperature" in kwargs and "temperature" in msg and "unsupported_value" in msg:
                self._supports_temperature = False
                kwargs.pop("temperature")
                return self._client.chat.completions.create(**kwargs)
            raise

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        resp = self._create(
            model=self._model,
            temperature=temperature,
            messages=[{"role": "user", "content": prompt}],
        )
        return (resp.choices[0].message.content or "").strip()

    def complete_vision(self, prompt, image_bytes, *, mime_type="image/jpeg", temperature=0.0):
        import base64

        b64 = base64.b64encode(image_bytes).decode()
        resp = self._create(
            model=os.getenv("OPENAI_VISION_MODEL", self._model),
            temperature=temperature,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                ],
            }],
        )
        return (resp.choices[0].message.content or "").strip()
