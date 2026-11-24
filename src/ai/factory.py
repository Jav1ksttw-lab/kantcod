"""Выбор провайдера ИИ. Настройка — переменные окружения, не репозиторий."""
from __future__ import annotations

import os
import sys

from ..config import Config
from .base import AIProvider, AIUnavailable
from .gigachat import GigaChatProvider
from .ollama import OllamaProvider
from .rules import RulesOnlyProvider


def create_provider(cfg: Config, override: str | None = None, strict: bool = False) -> AIProvider:
    provider = (override or cfg.ai_provider or "auto").lower()

    if provider == "gigachat":
        has_token = bool(os.getenv("GIGACHAT_ACCESS_TOKEN"))
        has_creds = bool(os.getenv("GIGACHAT_CLIENT_ID") and os.getenv("GIGACHAT_CLIENT_SECRET"))
        if not has_token and not has_creds:
            raise AIUnavailable(
                "Для GigaChat нужны GIGACHAT_CLIENT_ID и GIGACHAT_CLIENT_SECRET "
                "(или GIGACHAT_ACCESS_TOKEN). См. .env.example"
            )
        return GigaChatProvider(cfg.gigachat_model, cfg.temperature)

    if provider == "ollama":
        instance = OllamaProvider(cfg.ollama_model, cfg.ollama_url, cfg.temperature)
        if not instance.available():
            raise AIUnavailable(
                f"Ollama недоступна по адресу {cfg.ollama_url}. "
                f"Установите Ollama, выполните `ollama pull {cfg.ollama_model}` и повторите запуск."
            )
        return instance

    if provider == "rules":
        return RulesOnlyProvider()

    if provider != "auto":
        raise AIUnavailable(f"Неизвестный AI_PROVIDER={provider!r}. Возможные значения: auto, gigachat, ollama, rules")

    has_giga = bool(
        os.getenv("GIGACHAT_ACCESS_TOKEN")
        or (os.getenv("GIGACHAT_CLIENT_ID") and os.getenv("GIGACHAT_CLIENT_SECRET"))
    )
    if has_giga:
        return GigaChatProvider(cfg.gigachat_model, cfg.temperature)

    ollama = OllamaProvider(cfg.ollama_model, cfg.ollama_url, cfg.temperature)
    if ollama.available():
        return ollama

    if strict:
        raise AIUnavailable(
            "ИИ не настроен. Укажите ключ GIGACHAT_CLIENT_ID/GIGACHAT_CLIENT_SECRET "
            f"или установите Ollama и модель {cfg.ollama_model}. См. .env.example"
        )
    print(
        "[WARN] ИИ не настроен: используется rules-only. Для полного прогона задайте "
        "GIGACHAT_* или запустите Ollama с моделью qwen2.5:3b (без аккаунта).",
        file=sys.stderr,
    )
    return RulesOnlyProvider()
