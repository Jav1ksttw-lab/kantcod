"""GigaChat (Сбер). Авторизация по client_id/client_secret или готовому token."""
from __future__ import annotations

import base64
import os
import time
import uuid
from typing import Any

import requests

from .base import AIProvider, AIUnavailable

AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"


class GigaChatProvider(AIProvider):
    name = "gigachat"

    def __init__(
        self,
        model: str = "GigaChat",
        temperature: float = 0.1,
        timeout: int = 30,
        verify_ssl: bool = False,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.timeout = timeout
        self.verify_ssl = verify_ssl
        self.client_id = os.getenv("GIGACHAT_CLIENT_ID", "")
        self.client_secret = os.getenv("GIGACHAT_CLIENT_SECRET", "")
        self.scope = os.getenv("GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
        self.auth_url = os.getenv("GIGACHAT_AUTH_URL", AUTH_URL)
        self.api_url = os.getenv("GIGACHAT_API_URL", API_URL)
        self._token = os.getenv("GIGACHAT_ACCESS_TOKEN", "")
        self._expires_at = time.time() + (1800 if self._token else 0)

    def _refresh_token(self) -> str:
        if self._token and time.time() < self._expires_at:
            return self._token
        if not self.client_id or not self.client_secret:
            raise AIUnavailable(
                "Для GigaChat нужны GIGACHAT_CLIENT_ID и GIGACHAT_CLIENT_SECRET "
                "(или GIGACHAT_ACCESS_TOKEN). См. .env.example"
            )
        credentials = base64.b64encode(f"{self.client_id}:{self.client_secret}".encode()).decode()
        headers = {
            "Authorization": f"Basic {credentials}",
            "RqUID": str(uuid.uuid4()),
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        try:
            response = requests.post(
                self.auth_url,
                headers=headers,
                data={"scope": self.scope},
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            payload: dict[str, Any] = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AIUnavailable(f"Ошибка авторизации GigaChat: {exc}") from exc
        if response.status_code != 200 or not payload.get("access_token"):
            raise AIUnavailable(
                f"Авторизация GigaChat не удалась: HTTP {response.status_code} {str(payload)[:300]}"
            )
        self._token = payload["access_token"]
        self._expires_at = time.time() + int(payload.get("expires_in", 1800)) - 60
        return self._token

    def complete(self, system: str, user: str) -> str:
        token = self._refresh_token()
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Request-ID": str(uuid.uuid4()),
        }
        try:
            response = requests.post(
                self.api_url,
                json=body,
                headers=headers,
                timeout=self.timeout,
                verify=self.verify_ssl,
            )
            payload: dict[str, Any] = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise AIUnavailable(f"Ошибка запроса к GigaChat: {exc}") from exc
        if response.status_code != 200:
            raise AIUnavailable(f"GigaChat вернул HTTP {response.status_code}: {str(payload)[:300]}")
        try:
            return payload["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise AIUnavailable(f"Неожиданный ответ GigaChat: {str(payload)[:300]}") from exc
