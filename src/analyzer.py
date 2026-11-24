"""Правила и проверка неоднозначных формулировок локальной или облачной моделью."""
from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from .ai.base import AIProvider, AIUnavailable
from .config import Config
from .facts import ambiguity_candidates, build_facts, rule_findings
from .prompt import SYSTEM_PROMPT, build_user_prompt


def parse_model_response(raw: str, count: int) -> list[int]:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.IGNORECASE)
    try:
        findings = json.loads(raw)["findings"]
        if not isinstance(findings, list) or any(type(item) is not int or not 1 <= item <= count for item in findings):
            raise ValueError("ожидались номера пунктов")
    except (ValueError, TypeError, KeyError) as exc:
        raise AIUnavailable("Модель вернула некорректный список замечаний") from exc
    return list(dict.fromkeys(findings))


def analyze_one(vacancy: dict[str, Any], provider: AIProvider, cfg: Config) -> tuple[dict[str, Any], str | None]:
    facts = build_facts(vacancy)
    findings = rule_findings(vacancy, facts)
    ai_error = None

    if provider.name != "rules":
        candidates = ambiguity_candidates(facts)
        if candidates:
            try:
                response = provider.complete(SYSTEM_PROMPT, build_user_prompt(facts, candidates, cfg.max_chars_per_field))
                for index in parse_model_response(response, len(candidates)):
                    findings.append({**candidates[index - 1], "origin": "ai"})
            except AIUnavailable as exc:
                ai_error = str(exc)

    entry = {
        "id": vacancy.get("id"),
        "url": vacancy.get("vac_url") or vacancy.get("url") or None,
        "findings": findings,
    }
    return entry, ai_error


def analyze_all(
    vacancies: list[dict[str, Any]], provider: AIProvider, cfg: Config
) -> tuple[list[dict[str, Any]], list[str]]:
    if not vacancies:
        return [], []
    entries = []
    errors = []
    workers = min(cfg.ai_workers, len(vacancies))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(analyze_one, vacancy, provider, cfg) for vacancy in vacancies]
        for future in futures:
            entry, error = future.result()
            entries.append(entry)
            if error:
                errors.append(f"{entry['id']}: {error}")
    return entries, errors
