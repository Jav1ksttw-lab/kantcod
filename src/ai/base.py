from __future__ import annotations

from abc import ABC, abstractmethod


class AIUnavailable(RuntimeError):
    """Провайдер ИИ недоступен или неправильно настроен."""


class AIProvider(ABC):
    name = "base"
    model = ""

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Вернуть текст ответа модели на коротком запросе анализа вакансии."""

    def close(self) -> None:
        return None
