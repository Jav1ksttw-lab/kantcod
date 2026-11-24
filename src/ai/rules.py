"""Офлайн-режим без ИИ: только детерминированные правила.

Используется для smoke-тестов и как последний резерв в режиме auto.
Для оценки критерия «ИИ влияет на отчёт» запускайте gigachat или ollama.
"""
from __future__ import annotations

from .base import AIProvider


class RulesOnlyProvider(AIProvider):
    name = "rules"
    model = "none"

    def complete(self, system: str, user: str) -> str:
        return '{"findings": []}'
