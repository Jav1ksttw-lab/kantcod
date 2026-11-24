"""Локальный сервер llama.cpp с OpenAI-совместимым интерфейсом."""
from __future__ import annotations

import requests

from .base import AIProvider, AIUnavailable


class LlamaCppProvider(AIProvider):
    name = "llamacpp"

    def __init__(self, model: str, url: str, temperature: float) -> None:
        self.model = model
        self.url = url.rstrip("/")
        self.temperature = temperature

    def complete(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": self.temperature,
            "max_tokens": 160,
        }
        try:
            response = requests.post(f"{self.url}/v1/chat/completions", json=body, timeout=420)
            response.raise_for_status()
            result = response.json()["choices"][0]["message"]["content"]
            if not isinstance(result, str) or not result.strip():
                raise ValueError("пустой ответ")
        except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as exc:
            raise AIUnavailable(f"Ошибка llama.cpp: {exc}") from exc
        return result
