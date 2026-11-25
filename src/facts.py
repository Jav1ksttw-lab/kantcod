"""Детерминированный слой: нормализация полей API и объектные замечания.

AI не заменяет этот слой, а дополняет его: здесь находятся пропуски и
проверяемые противоречия, в ai/* — неоднозначные формулировки.
"""
from __future__ import annotations

import re
from html import unescape
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

_DETAIL_FIELDS = ("duty", "requirements", "qualification", "requirement.qualification", "term.text", "conditions")
_EDU_WORDS = r"образован|бакалавр|магистр|специалитет|диплом"
_SCHEDULE_WORDS = r"график|сменн|смен[аы]|(?:[0-2]?\d[:.][0-5]\d)|[1-7]\s*[/хx×]\s*[1-7]|рабоч(?:ий|его) (?:день|дня)|пн\s*[–—-]\s*пт"
_ADDRESS_WORDS = r"\b(?:ул(?:ица)?\.|улица|проспект|пр-т|шоссе|пер\.|переулок)\s+[^,.]+[, ]+\d|\bдом\s+\d|дистанционная работа|удал[её]нная работа"
_EMPLOYMENT_WORDS = r"\b(?:полная|частичная|неполная|временная|сезонная) занятость\b|\b(?:на )?0[.,]5 ставки\b|\bполставки\b"


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", value))).strip()
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
    requirement = _mapping(vacancy.get("requirement"))
    addresses = _mapping(vacancy.get("addresses"))
    address_list = addresses.get("address") or []
    if isinstance(address_list, dict):
        address_list = [address_list]
    if not isinstance(address_list, list):
        address_list = []
    locations = [text(a.get("location")) for a in address_list if isinstance(a, dict)]
    term = vacancy.get("term")
    company = _mapping(vacancy.get("company"))
    shift = vacancy.get("shift") or []
    return {
        "job-name": text(vacancy.get("job-name")),
        "duty": text(vacancy.get("duty")),
        "requirements": text(vacancy.get("requirements")),
        "requirement.qualification": text(requirement.get("qualification")),
        "requirement.education": text(requirement.get("education")),
        "requirement.experience": text(requirement.get("experience")),
        "skills": text(vacancy.get("skills")),
        "qualification": text(vacancy.get("qualification")),
        "salary": text(vacancy.get("salary")),
        "salary_min": text(vacancy.get("salary_min")),
        "salary_max": text(vacancy.get("salary_max")),
        "schedule": text(vacancy.get("schedule")),
        "shift": text(shift),
        "term.text": text(term.get("text") if isinstance(term, dict) else term),
        "conditions": text(vacancy.get("conditions")),
        "workPlaceType": text(vacancy.get("workPlaceType")),
        "currency": text(vacancy.get("currency")),
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
    value_fields: list[str] | None = None,
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
    if value_fields:
        finding["value_fields"] = value_fields
    return finding


def _omission(field: str, topic: str, issue: str, question: str) -> dict[str, Any]:
    return make_finding("omission", topic, field, issue, question)


def _contradiction(
    topic: str, facts: dict[str, str], first: str, second: str, issue: str, recommendation: str,
    second_quote: str | None = None,
) -> dict[str, Any]:
    values = [facts[first], second_quote or facts[second]]
    return make_finding(
        "contradiction", topic, first, issue, recommendation,
        quote=" ↔ ".join(values), values=values, value_fields=[first, second],
    )


_AMOUNT = r"(?:[1-9]\d{0,2}(?:[ .]\d{3})+|[1-9]\d*)"
_SALARY_LABEL = re.compile(
    rf"(?:(от|до)\s+)?({_AMOUNT})(?:\s*(?:до|[-–—])\s*({_AMOUNT}))?(?:\s*(?:руб(?:\.|лей)?|₽))?",
    re.IGNORECASE,
)
_SALARY_IN_TEXT = rf"(?:зарплат\w*|оплат\w*|оклад\w*)[^.\d]{{0,35}}{_AMOUNT}|{_AMOUNT}\s*(?:руб\b|рублей\b|₽)"


def _amount(value: str) -> int | None:
    digits = value.replace(" ", "").replace(".", "")
    return int(digits) if re.fullmatch(r"[1-9]\d{0,12}", digits) else None


def _salary_range(value: str) -> tuple[int | None, int | None]:
    match = _SALARY_LABEL.fullmatch(value)
    if match is None:
        return None, None
    prefix, first, second = match.groups()
    if second:
        return _amount(first), _amount(second)
    if prefix and prefix.lower() == "до":
        return None, _amount(first)
    if prefix:
        return _amount(first), None
    amount = _amount(first)
    return amount, amount


def rule_findings(vacancy: dict[str, Any], facts: dict[str, str]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    details = " ".join(facts[field] for field in _DETAIL_FIELDS)
    salary_min = _amount(facts["salary_min"])
    salary_max = _amount(facts["salary_max"])

    if is_empty(facts["job-name"]):
        findings.append(_omission("job-name", "название должности",
                                  "Название должности не указано.", "Как называется должность?"))
    if is_empty(facts["duty"]) and not re.search(r"обязанности\s*[:–—-]\s*\w", details, re.I):
        findings.append(_omission("duty", "обязанности",
                                  "В карточке нет списка обязанностей.", "Какие задачи нужно выполнять каждый день?"))
    if all(is_empty(facts[field]) for field in (
        "requirements", "requirement.qualification", "qualification", "requirement.experience", "skills",
    )) and not re.search(r"требования\s*[:–—-]\s*\w", details, re.I):
        findings.append(_omission("requirements", "требования",
                                  "Профессиональные требования не указаны.", "Какие навыки и опыт нужны для этой работы?"))
    if is_empty(facts["requirement.education"]) and not re.search(_EDU_WORDS, details, re.I):
        findings.append(_omission("requirement.education", "требования",
                                  "Требования к образованию не указаны.", "Какое образование требуется, если это важно для работы?"))
    if is_empty(facts["salary"]) and salary_min is None and salary_max is None and not re.search(
        _SALARY_IN_TEXT, details, re.I
    ):
        findings.append(_omission("salary", "оплата труда",
                                  "В карточке нет суммы оплаты.", "Какая сумма или диапазон оплаты предусмотрены?"))
    if is_empty(facts["schedule"]) and is_empty(facts["shift"]) and not re.search(_SCHEDULE_WORDS, details, re.I):
        findings.append(_omission("schedule", "график работы",
                                  "График не указан.", "В какие дни и часы нужно работать? Есть ли смены?"))
    if is_empty(facts["addresses.address[].location"]) and not re.search(
        _ADDRESS_WORDS, details + " " + facts["workPlaceType"], re.I
    ):
        findings.append(_omission("addresses.address[].location", "место работы",
                                  "Адрес и формат работы не указаны.", "По какому адресу нужно работать? Возможна ли удалённая работа?"))
    if is_empty(facts["employment"]) and not re.search(_EMPLOYMENT_WORDS, details, re.I):
        findings.append(_omission("employment", "тип занятости",
                                  "В карточке не указан тип занятости.", "Это полная или частичная занятость? На какую ставку?"))

    if salary_min is not None and salary_max is not None and salary_min > salary_max:
        findings.append(_contradiction(
            "оплата труда", facts, "salary_min", "salary_max", "Нижняя граница оплаты превышает верхнюю.",
            "Какая сумма минимальная и какая максимальная?",
        ))

    text_low, text_high = _salary_range(facts["salary"])
    min_mismatch = salary_min is not None and (
        (text_low is not None and text_low != salary_min)
        or (text_high is not None and salary_min > text_high)
    )
    max_mismatch = salary_max is not None and (
        (text_low is not None and salary_max < text_low)
        or (text_high is not None and text_high != salary_max)
    )
    if min_mismatch or max_mismatch:
        boundary = "salary_min" if min_mismatch else "salary_max"
        findings.append(_contradiction(
            "оплата труда", facts, "salary", boundary,
            "Суммы в полях оплаты расходятся.",
            "Какой диапазон оплаты должен быть в карточке?",
        ))

    conflicts = (
        ("employment", "тип занятости", "полная занятость",
         r"\b(?:частичная|неполная) занятость\b|\bполставки\b|\b0[.,]5 ставки\b",
         "Предлагается полная или частичная занятость? На какую ставку?"),
        ("schedule", "график работы", "полный рабочий день",
         r"\b(?:неполный|сокращ[её]нный) рабочий день\b",
         "Сколько часов длится рабочий день?"),
    )
    for field, topic, label, pattern, question in conflicts:
        if not re.search(rf"\b{label}\b", facts[field], re.I):
            continue
        for detail_field in _DETAIL_FIELDS:
            matched = re.search(pattern, facts[detail_field], re.I)
            if matched and not re.search(r"\b(?:возможн\w*|или|вариант\w*|по согласованию)\b", facts[detail_field], re.I):
                findings.append(_contradiction(
                    topic, facts, field, detail_field,
                    "В карточке указаны разные условия.", question, matched.group(),
                ))
                break

    return findings


_WORK_HOURS = r"\b(?:[01]?\d|2[0-3])[:.][0-5]\d\s*(?:до|[-–—])\s*(?:[01]?\d|2[0-3])[:.][0-5]\d\b"
_WORK_DAYS = (
    r"\b(?:[1-7]\s*[/хx×]\s*[1-7]|по будням|будние дни|"
    r"понедельника по пятницу|пн\.?\s*(?:[-–—]|по)\s*пт)\b"
)


def ambiguity_candidates(facts: dict[str, str]) -> list[dict[str, Any]]:
    """Выбирает фрагменты для проверки в контексте остальной карточки."""
    details = " ".join(facts[field] for field in _DETAIL_FIELDS)
    schedule_text = " ".join((facts["schedule"], facts["shift"], details))
    hours_known = bool(re.search(_WORK_HOURS, schedule_text, re.I))
    days_known = bool(re.search(_WORK_DAYS, schedule_text, re.I))
    schedule_issue = "Из карточки неясно, в какие дни и часы предстоит работать."
    schedule_question = "В какие дни и часы нужно работать? Как согласуются смены?"
    if hours_known:
        schedule_issue = "В карточке указаны часы, но не уточнены рабочие дни."
        schedule_question = "В какие дни нужно работать и как согласуются смены?"
    elif days_known:
        schedule_issue = "В карточке указаны рабочие дни, но не уточнены часы."
        schedule_question = "Во сколько начинается и заканчивается рабочий день или смена?"

    checks = [
        ("название должности", ("job-name",),
         r"^(?:специалист|сотрудник|работник|менеджер|эксперт|помощник)$",
         "Название не раскрывает специализацию.", "Какое направление работы и специализацию указать в названии?"),
        ("обязанности", ("duty",),
         r"(?<!\w)(?:иные поручения|поручения руководителя|работа с документами|работа с клиентами)",
         "Формулировка обязанностей слишком общая.", "Какие задачи сотрудник выполняет регулярно?"),
        ("требования", ("requirements", "requirement.qualification", "qualification"),
         r"нужен опыт|опыт работы обязателен|соответствующ\w* опыт|знание ПК|уверенный пользователь ПК",
         "Требования можно истолковать по-разному.", "Какой опыт, навыки или знание программ требуются?"),
        ("оплата труда", ("salary", *_DETAIL_FIELDS),
         r"по договор[её]нности|по результатам|по итогам собеседования|достойная зарплата",
         "Размер оплаты нельзя определить по формулировке.", "На какую сумму или диапазон оплаты может рассчитывать соискатель?"),
        ("график работы", ("schedule", "shift", *_DETAIL_FIELDS),
         r"гибкий график|сменный график|сменная работа|по согласованию|скользящий график",
         schedule_issue, schedule_question),
        ("место работы", ("addresses.address[].location",),
         r"^(?:Калининградская область|Калининград(?:,?\s*г\.)?|г\.\s*Калининград|территория работодателя)$",
         "Место указано без точного адреса.", "В каком населённом пункте и по какому адресу находится рабочее место?"),
        ("тип занятости", ("employment",),
         r"по договор[её]нности|по согласованию|другое|иная занятость",
         "Из формулировки неясен тип занятости.", "Это полная или частичная занятость? На какую ставку?"),
    ]
    pay_known = any(_amount(facts[field]) is not None for field in ("salary_min", "salary_max"))
    pay_known |= _salary_range(facts["salary"]) != (None, None) or bool(re.search(_SALARY_IN_TEXT, details, re.I))
    candidates = []
    for topic, fields, pattern, issue, recommendation in checks:
        if (topic == "оплата труда" and pay_known) or (topic == "график работы" and days_known and hours_known):
            continue
        for field in fields:
            match = re.search(pattern, facts[field], re.I)
            if match:
                candidates.append(make_finding("ambiguity", topic, field, issue, recommendation, match.group()))
                break
    return candidates
