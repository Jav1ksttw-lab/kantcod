"""Дополнительный сценарий: черновик резюме под вакансию.

Опыт, навыки и образование берутся ТОЛЬКО из исходного (вымышленного) резюме,
в вакансии используются название, обязанности и требования.
"""
from __future__ import annotations

import json
from typing import Any

from .ai.base import AIProvider
from .config import Config
from .facts import build_facts

SYSTEM = """Ты помогаешь соискателю подготовить черновик резюме под конкретную вакансию.
Используй ТОЛЬКО факты из предоставленного резюме: опыт, навыки, образование, контакты. Имя и факты не выдумывай.
Из вакансии можно взять только название должности и формулировки требований/обязанностей для раздела «Почему подхожу».
Не приписывай соискателю опыт, которого нет в исходном резюме. Не указывай зарплатные ожидания, если их нет в резюме.
Верни markdown с разделами: «Цель», «Опыт», «Навыки», «Образование», «Почему подхожу». Без пояснений от модели."""


def load_vacancies(path: str | None, cfg: Config) -> list[dict[str, Any]]:
    from .fetcher import extract_vacancies

    source = path or str(cfg.last_input_path)
    with open(source, encoding="utf-8") as handle:
        payload = json.load(handle)
    vacancies = extract_vacancies(payload)
    if not vacancies:
        raise ValueError(f"В файле {source} не найдено вакансий в формате ответа API")
    return vacancies


def find_vacancy(vacancies: list[dict[str, Any]], vacancy_id: str) -> dict[str, Any]:
    for vacancy in vacancies:
        if str(vacancy.get("id")) == vacancy_id:
            return vacancy
    raise ValueError(f"Вакансия {vacancy_id} не найдена. Доступные ID: {', '.join(str(v.get('id')) for v in vacancies[:10])}")


def draft_resume(vacancy: dict[str, Any], resume: dict[str, Any], provider: AIProvider, cfg: Config) -> str:
    facts = build_facts(vacancy)
    user = (
        "Исходное резюме (единственный источник фактов о соискателе):\n"
        + json.dumps(resume, ensure_ascii=False, indent=2)
        + "\n\nВыбранная вакансия:\n"
        + json.dumps(
            {k: facts[k] for k in ("job-name", "duty", "requirements", "requirement.qualification", "requirement.education") if facts[k]},
            ensure_ascii=False,
            indent=2,
        )
    )
    return provider.complete(SYSTEM, user).strip()
