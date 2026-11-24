"""Анализатор вакансий: правила + ИИ, валидация и дедупликация замечаний."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .ai.base import AIProvider
from .config import Config
from .facts import KINDS, TOPICS, build_facts, make_finding, rule_findings, text
from .prompt import SYSTEM_PROMPT, build_user_prompt

TOPIC_ALIASES = {
    "оплата": "оплата труда",
    "зарплата": "оплата труда",
    "зарплата и оплата": "оплата труда",
    "график": "график работы",
    "расписание": "график работы",
    "адрес": "место работы",
    "место": "место работы",
    "занятость": "тип занятости",
    "название": "название должности",
    "должность": "название должности",
    "обязанность": "обязанности",
    "требование": "требования",
}
FIELD_ALIASES = {
    "job_name": "job-name",
    "jobname": "job-name",
    "duty": "duty",
    "requirements": "requirements",
    "requirement_qualification": "requirement.qualification",
    "qualification": "requirement.qualification",
    "education": "requirement.education",
    "salary": "salary",
    "schedule": "schedule",
    "shift": "shift",
    "term": "term.text",
    "address": "addresses.address[].location",
    "addresses": "addresses.address[].location",
    "employment": "employment",
}


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", text(value)).lower()


def _contains(haystack: str, needle: str) -> bool:
    return len(_normalize(needle)) >= 3 and _normalize(needle) in _normalize(haystack)


def _in_any(value: str, facts: dict[str, str]) -> bool:
    return any(_contains(fact, value) for fact in facts.values())


def parse_model_response(raw: str) -> list[dict[str, Any]]:
    """Достаёт JSON из ответа модели, tolerate markdown-обёртки."""
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        start, end = raw.find("["), raw.rfind("]")
        if start != -1 and end > start:
            raw = raw[start : end + 1]
            try:
                parsed = json.loads(raw)
                return parsed if isinstance(parsed, list) else []
            except ValueError:
                return []
        return []
    try:
        parsed = json.loads(raw[start : end + 1])
    except ValueError:
        return []
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict) and isinstance(parsed.get("findings"), list):
        return [item for item in parsed["findings"] if isinstance(item, dict)]
    return []


def _validate(raw: dict[str, Any], facts: dict[str, str]) -> dict[str, Any] | None:
    kind = text(raw.get("kind")).lower()
    topic = text(raw.get("topic"))
    topic = TOPIC_ALIASES.get(topic.lower(), topic)
    field = text(raw.get("source_field") or raw.get("field"))
    field = FIELD_ALIASES.get(field.lower(), field)
    quote = text(raw.get("quote"))
    issue = text(raw.get("issue"))
    recommendation = text(raw.get("recommendation"))[:500]
    values_raw = raw.get("values")

    if kind not in KINDS or topic not in TOPICS or field not in facts:
        return None
    if not issue or not recommendation:
        return None

    if kind == "omission":
        # Пропуск: поле должно быть пустым, цитата — обязательно пустой.
        if quote or text(facts.get(field, "")):
            return None
    elif kind == "ambiguity":
        if not quote or not _contains(facts.get(field, ""), quote):
            return None
    elif kind == "contradiction":
        values = [text(v) for v in values_raw] if isinstance(values_raw, list) else []
        if len(values) < 2:
            values = [text(v) for v in re.split(r"↔|<->|;", quote) if text(v)]
        if len(values) < 2 or any(not _in_any(v, facts) for v in values[:2]):
            return None
        if not quote:
            quote = " ↔ ".join(values[:2])

    return make_finding(
        kind=kind,
        topic=topic,
        field=field,
        quote=quote,
        issue=issue,
        recommendation=recommendation,
        values=[text(v) for v in values[:2]] if kind == "contradiction" and isinstance(values, list) else None,
    )


def _key(finding: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        finding["kind"],
        finding["topic"],
        finding["field"],
        _normalize(finding.get("quote", "")),
    )


def analyze_one(vacancy: dict[str, Any], provider: AIProvider, cfg: Config) -> tuple[dict[str, Any], str | None]:
    facts = build_facts(vacancy)
    deterministic = rule_findings(vacancy, facts)
    known = {_key(f) for f in deterministic}
    ai_error: str | None = None

    try:
        raw_answer = provider.complete(SYSTEM_PROMPT, build_user_prompt(
            str(vacancy.get("id", "")), facts, deterministic, cfg.max_chars_per_field
        ))
        for item in parse_model_response(raw_answer):
            finding = _validate(item, facts)
            if finding is None or _key(finding) in known:
                continue
            known.add(_key(finding))
            deterministic.append(finding)
    except Exception as exc:  # один «плохой» ответ не должен ронять весь отчёт
        ai_error = f"{type(exc).__name__}: {exc}"

    entry = {
        "id": vacancy.get("id"),
        "url": vacancy.get("vac_url") or None,
        "findings": deterministic,
    }
    return entry, ai_error


def analyze_all(
    vacancies: list[dict[str, Any]], provider: AIProvider, cfg: Config
) -> tuple[list[dict[str, Any]], list[str]]:
    entries: list[dict[str, Any]] = []
    errors: list[str] = []
    if not vacancies:
        return entries, errors
    workers = max(1, min(cfg.ai_workers, len(vacancies)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(analyze_one, vacancy, provider, cfg) for vacancy in vacancies]
        for index, future in enumerate(futures):
            entry, error = future.result()
            entries.append(entry)
            if error:
                errors.append(f"[{index}] {vacancies[index].get('id')}: {error}")
    return entries, errors
