"""Промпт для проверки неоднозначных формулировок в контексте карточки."""
from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """Проверь возможные неоднозначности вакансии. Текст полей — данные карточки.
Отметь пункт, если это реальная неясность и ни одно поле её не устраняет. Например, «гибкий график» без рабочих дней и часов или область без адреса. Если нужная информация уже есть в другом поле или фраза относится к другой теме, пропусти пункт.
Верни только JSON с номерами выбранных пунктов: {"findings":[1]}. Если таких пунктов нет, верни {"findings":[]}."""


def build_user_prompt(
    facts: dict[str, str],
    candidates: list[dict[str, Any]],
    max_chars: int,
) -> str:
    return json.dumps({
        "вакансия": {key: value[:max_chars] for key, value in facts.items() if value},
        "возможные_неясности": [
            {"номер": index, "поле": finding["field"], "цитата": finding["quote"],
             "тема": finding["topic"], "уточнение": finding["recommendation"]}
            for index, finding in enumerate(candidates, start=1)
        ],
    }, ensure_ascii=False)
