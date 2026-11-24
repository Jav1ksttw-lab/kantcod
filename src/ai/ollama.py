"""Локальная модель Ollama — путь для жюри без аккаунта и ключей."""
from __future__ import annotations

from typing import Any

import requests

from .base import AIProvider, AIUnavailable


class OllamaProvider(AIProvider):
    name = "ollama"

    def __init__(self, model: str, url: str = "http://localhost:11434", temperature: float = 0.1, timeout: int = 120) -> None:
        self.model = model
        self.url = url.rstrip("/")
        self.temperature = temperature
        self.timeout = timeout

    def available(self) -> bool:
        try:
            response = requests.get(f"{self.url}/api/tags", timeout=3)
            return response.status_code == 200
        except requests.RequestException:
            return False

    def complete(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "format": "json",
            "options": {"temperature": self.temperature},
        }
        try:
            response = requests.post(f"{self.url}/api/chat", json=body, timeout=self.timeout)
            payload: dict[str, Any] = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AIUnavailable(f"Ollama недоступна: {exc}. Установите Ollama и ollama pull {self.model}") from exc
        if response.status_code != 200:
            raise AIUnavailable(f"Ollama вернула HTTP {response.status_code}: {str(payload)[:300]}")
        return str((payload.get("message") or {}).get("content", ""))
