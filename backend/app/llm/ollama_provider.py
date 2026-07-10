"""Local Ollama backend (the original, still ideal for a dev box with a GPU)."""

from __future__ import annotations

import os

from .base import LLMProvider


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self) -> None:
        # ``ollama`` is only imported/needed when this provider is selected.
        import ollama

        self._ollama = ollama
        self._model = os.getenv("OLLAMA_MODEL", "gemma3:12b")
        self._num_ctx = int(os.getenv("OLLAMA_NUM_CTX", "5000"))
        host = os.getenv("OLLAMA_HOST")  # e.g. http://<ollama-host>:11434 for a remote box
        self._client = ollama.Client(host=host) if host else ollama.Client()

    def complete(self, prompt: str, *, temperature: float = 0.0) -> str:
        response = self._client.chat(
            model=self._model,
            options=self._ollama.Options(temperature=temperature, num_ctx=self._num_ctx),
            messages=[{"role": "user", "content": prompt}],
        )
        return response["message"]["content"].strip()

    def complete_vision(self, prompt, image_bytes, *, mime_type="image/jpeg", temperature=0.0):
        import base64

        b64 = base64.b64encode(image_bytes).decode()
        response = self._client.chat(
            model=os.getenv("OLLAMA_VISION_MODEL", self._model),
            options=self._ollama.Options(temperature=temperature),
            messages=[{"role": "user", "content": prompt, "images": [b64]}],
        )
        return response["message"]["content"].strip()
