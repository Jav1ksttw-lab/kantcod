"""Детерминированный слой: нормализация полей API и объектные замечания.

AI не заменяет этот слой, а дополняет его: здесь находятся пропуски и
проверяемые противоречия, в ai/* — неоднозначные формулировки.
"""
from __future__ import annotations

import re
from typing import Any

TOPICS = {
    "название должности",
    "обязанности",
    "требования",
    "оплата труда",
    "график работы",
    "место работы",
    "тип занятости",
}

KINDS = {"omission", "ambiguity", "contradiction"}

_PLACEHOLDERS = {"", "нет", "не указано", "не заполнено", "отсутствует", "-", "—", "n/a", "none", "?"}

_EDU_WORDS = (
    "образование", "класс", "бакалавр", "магистр", "специалитет", "курс",
    "профессиональн", "Technical", "не предъявляются", "не предъявляется",
)
_SCHEDULE_WORDS = (
    "график", "смена", "сменн", "смены", "смены", "9.00", "18.00", "5/2", "5х2",
    "2/2", "2х2", "недель", "выходн", "суббот", "воскрес", "утренн", "вечерн",
    "полный рабочий день", "неполный рабочий день", "гибк", "по согласованию",
)


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "; ".join(text(v) for v in value if text(v))
    if isinstance(value, dict):
        return "; ".join(f"{k}: {text(v)}" for k, v in value.items() if text(v))
    return re.sub(r"\s+", " ", str(value)).strip()


def is_empty(value: str) -> bool:
    return text(value).lower().rstrip(".") in _PLACEHOLDERS


def build_facts(vacancy: dict[str, Any]) -> dict[str, str]:
    """Карта «имя поля API -> нормализованное значение»."""
    requirement = vacancy.get("requirement") or {}
    addresses = vacancy.get("addresses") or {}
    address_list = addresses.get("address") or []
    locations = [text(a.get("location")) for a in address_list if isinstance(a, dict)]
    term = vacancy.get("term") or {}
    company = vacancy.get("company") or {}
    shift = vacancy.get("shift") or []
    return {
        "job-name": text(vacancy.get("job-name")),
        "duty": text(vacancy.get("duty")),
        "requirements": text(vacancy.get("requirements")),
        "requirement.qualification": text(requirement.get("qualification")),
        "requirement.education": text(requirement.get("education")),
        "qualification": text(vacancy.get("qualification")),
        "salary": text(vacancy.get("salary")),
        "salary_min": text(vacancy.get("salary_min")),
        "salary_max": text(vacancy.get("salary_max")),
        "schedule": text(vacancy.get("schedule")),
        "shift": text(shift),
        "term.text": text(term.get("text")),
        "addresses.address[].location": "; ".join(loc for loc in locations if loc),
        "employment": text(vacancy.get("employment")),
        "work_places": text(vacancy.get("work_places")),
        "company.name": text(company.get("name")),
    }


def make_finding(
    kind: str,
    topic: str,
    field: str,
    issue: str,
    recommendation: str,
    quote: str = "",
    values: list[str] | None = None,
) -> dict[str, Any]:
    finding: dict[str, Any] = {
        "kind": kind,
        "topic": topic,
        "field": field,
        "quote": text(quote),
        "issue": text(issue),
        "recommendation": text(recommendation),
    }
    if values:
        finding["values"] = [text(v) for v in values if text(v)]
    return finding


def _omission(facts: dict[str, str], field: str, topic: str, what: str) -> dict[str, Any]:
    return make_finding(
        "omission",
        topic,
        field,
        f"В вакансии нет сведений: {what}.",
        f"Уточните у работодателя и добавьте в карточку: {what}. Не выдумывайте значения.",
    )


def _has_info(facts: dict[str, str], words: tuple[str, ...], *fields: str) -> bool:
    blob = " ".join(facts.get(f, "") for f in fields).lower()
    return any(word.lower() in blob for word in words)


_SALARY_NUM = re.compile(r"(?<!\d)(\d[\d ]{2,})(?!\d)")


def _parse_salary_range(value: str) -> tuple[int | None, int | None]:
    clean = value.replace("\u00a0", " ").replace(" ", "")
    if "от" in clean.lower() and "до" in clean.lower():
        nums = re.findall(r"\d+", clean)
        if len(nums) >= 2:
            return int(nums[0]), int(nums[1])
    if "от" in clean.lower():
        nums = re.findall(r"\d+", clean)
        return (int(nums[0]), None) if nums else (None, None)
    if "до" in clean.lower():
        nums = re.findall(r"\d+", clean)
        return (None, int(nums[0])) if nums else (None, None)
    nums = [int(n.replace(" ", "")) for n in _SALARY_NUM.findall(value)]
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1:
        return nums[0], nums[0]
    return None, None


def rule_findings(vacancy: dict[str, Any], facts: dict[str, str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    # --- Пропуски ---
    if is_empty(facts["job-name"]):
        findings.append(_omission(facts, "job-name", "название должности", "точное название должности"))
    if is_empty(facts["duty"]):
        findings.append(_omission(facts, "duty", "обязанности", "перечень обязанностей"))
    if is_empty(facts["requirements"]) and is_empty(facts["requirement.qualification"]):
        findings.append(
            _omission(facts, "requirements", "требования", "профессиональные требования к соискателю")
        )
    if is_empty(facts["requirement.education"]) and not _has_info(
        facts, _EDU_WORDS, "requirements", "requirement.qualification", "qualification"
    ):
        findings.append(_omission(facts, "requirement.education", "требования", "требуемый уровень образования"))
    if is_empty(facts["salary"]) and is_empty(facts["salary_min"]):
        findings.append(_omission(facts, "salary", "оплата труда", "размер или диапазон оплаты"))
    if (
        is_empty(facts["schedule"])
        and is_empty(facts["shift"])
        and not _has_info(facts, _SCHEDULE_WORDS, "requirement.qualification", "term.text")
    ):
        findings.append(_omission(facts, "schedule", "график работы", "график работы и сменность"))
    if is_empty(facts["addresses.address[].location"]):
        findings.append(_omission(facts, "addresses.address[].location", "место работы", "адрес места работы"))
    if is_empty(facts["employment"]):
        findings.append(_omission(facts, "employment", "тип занятости", "тип занятости (полная/частичная)"))

    # --- Проверяемые противоречия ---
    salary_min = int(facts["salary_min"]) if facts["salary_min"].isdigit() else None
    salary_max = int(facts["salary_max"]) if facts["salary_max"].isdigit() else None
    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        findings.append(
            make_finding(
                "contradiction",
                "оплата труда",
                "salary_min",
                "Нижняя граница оплаты превышает верхнюю.",
                "Сверьте структурированные поля salary_min и salary_max и укажите корректный диапазон.",
                quote=f"{salary_min} ↔ {salary_max}",
                values=[str(salary_min), str(salary_max)],
            )
        )

    if facts["salary"]:
        text_low, text_high = _parse_salary_range(facts["salary"])
        if text_low is not None and salary_min is not None and text_low != salary_min:
            findings.append(
                make_finding(
                    "contradiction",
                    "оплата труда",
                    "salary",
                    "Текстовая формулировка оплаты не совпадает со структурированным минимумом.",
                    "Уточните у работодателя фактический размер оплаты и приведите текст и поле salary_min к одному значению.",
                    quote=f"{text_low} ↔ {salary_min}",
                    values=[str(text_low), str(salary_min)],
                )
            )
        min_above_high = text_high is not None and salary_min is not None and salary_min > text_high
        if text_high is not None and salary_max is not None and text_high != salary_max and not min_above_high:
            findings.append(
                make_finding(
                    "contradiction",
                    "оплата труда",
                    "salary",
                    "Текстовая верхняя граница оплаты не совпадает с полем salary_max.",
                    "Уточните верхнюю границу оплаты и обновите поле salary_max или текст вакансии.",
                    quote=f"{text_high} ↔ {salary_max}",
                    values=[str(text_high), str(salary_max)],
                )
            )
        if text_high is not None and text_low is None and salary_min is not None and salary_min > text_high:
            findings.append(
                make_finding(
                    "contradiction",
                    "оплата труда",
                    "salary",
                    "Указанный минимум оплаты выше текстовой верхней границы.",
                    "Сверьте текст вакансии и поле salary_min, укажите непротиворечивый диапазон.",
                    quote=f"до {text_high} ↔ от {salary_min}",
                    values=[f"до {text_high}", f"от {salary_min}"],
                )
            )
        if text_low is not None and salary_max is not None and text_low > salary_max:
            findings.append(
                make_finding(
                    "contradiction",
                    "оплата труда",
                    "salary",
                    "Указанный минимум оплаты выше структурированной верхней границы.",
                    "Сверьте текст вакансии и поле salary_max, укажите непротиворечивый диапазон.",
                    quote=f"от {text_low} ↔ до {salary_max}",
                    values=[f"от {text_low}", f"до {salary_max}"],
                )
            )

    other = " ".join(
        facts[f]
        for f in ("qualification", "requirement.qualification", "requirements", "term.text", "duty")
        if facts.get(f)
    ).lower()
    employment = facts["employment"].lower()
    for pattern in ("частичная занятость", "неполная занятость", "полставк", "0,5 ставк", "0.5 ставк"):
        if "полная занятость" in employment and pattern in other:
            match = re.search(r"[^\s,.;]*" + re.escape(pattern) + r"[^\s,.;]*", other)
            value = match.group(0) if match else pattern
            findings.append(
                make_finding(
                    "contradiction",
                    "тип занятости",
                    "employment",
                    "Поле занятости и описание дают разные сведения о полноте занятости.",
                    "Уточните, полная это занятость или частичная, и приведите поле employment и описание к одному значению.",
                    quote=f"{facts['employment']} ↔ {value}",
                    values=[facts["employment"], value],
                )
            )
            break

    schedule = facts["schedule"].lower()
    for pattern in ("неполный рабочий день", "сокращённый рабочий день", "сокращенный рабочий день"):
        if "полный рабочий день" in schedule and pattern in other:
            findings.append(
                make_finding(
                    "contradiction",
                    "график работы",
                    "schedule",
                    "Структурированный график и описание противоречат друг другу.",
                    "Уточните реальный график и длительность рабочего дня, затем обновите поле schedule или описание.",
                    quote=f"{facts['schedule']} ↔ {pattern}",
                    values=[facts["schedule"], pattern],
                )
            )
            break

    return findings
