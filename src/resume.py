"""Дополнительный сценарий: черновик резюме под вакансию.

Опыт, навыки и образование берутся ТОЛЬКО из исходного (вымышленного) резюме,
в вакансии используются название, обязанности и требования.
"""
from __future__ import annotations

import json
from typing import Any

from .ai.base import AIProvider, AIUnavailable
from .config import Config
from .facts import build_facts, text

SYSTEM = """Подбери сведения из резюме, относящиеся к вакансии. Используй только данные запроса.
Верни JSON формата {"highlights":[1,3]} с номерами максимум трёх подходящих пунктов резюме.
Если подходящих пунктов нет, верни {"highlights":[]}."""



def load_vacancies(path: str | None, cfg: Config) -> list[dict[str, Any]]:
    from .fetcher import extract_vacancies

    source = path or str(cfg.last_input_path)
    with open(source, encoding="utf-8-sig") as handle:
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
    if not isinstance(resume, dict):
        raise ValueError("Резюме должно быть JSON-объектом")
    experience = []
    education = []
    highlights = []
    skills = [text(item) for item in resume.get("skills", [])]
    for item in resume.get("experience", []):
        profile = " · ".join(text(item.get(key)) for key in ("role", "organization", "period") if item.get(key))
        experience.append(profile)
        duties = [text(duty) for duty in item.get("duties", [])]
        experience.extend(duties)
        highlights.extend(duties)
    highlights.extend(skills)
    for item in resume.get("education", []):
        profile = " · ".join(text(item.get(key)) for key in ("specialty", "institution", "year") if item.get(key))
        education.append(profile)
    highlights.extend(education)
    numbered = dict(enumerate(filter(None, highlights), start=1))
    user = json.dumps({
        "vacancy": {key: facts[key][:cfg.max_chars_per_field] for key in (
            "job-name", "duty", "requirements", "requirement.qualification", "requirement.education",
        ) if facts[key]},
        "resume_items": numbered,
    }, ensure_ascii=False)
    raw = provider.complete(SYSTEM, user).strip()
    try:
        indices = json.loads(raw)["highlights"]
        if not isinstance(indices, list):
            raise TypeError
    except (ValueError, KeyError, TypeError) as exc:
        raise AIUnavailable("Модель не вернула список пунктов резюме") from exc
    selected = list(dict.fromkeys(index for index in indices if type(index) is int and index in numbered))[:3]
    sections = {
        "Опыт": experience,
        "Навыки": skills,
        "Образование": education,
        "Почему подхожу": [numbered[index] for index in selected],
    }
    lines = [f"# {text(resume.get('name')) or 'Черновик резюме'}", "", "## Цель", "",
             facts["job-name"] or text(resume.get("position"))]
    for section, items in sections.items():
        lines.extend(["", f"## {section}", ""])
        lines.extend(f"- {item}" for item in items if item)
    return "\n".join(lines)
