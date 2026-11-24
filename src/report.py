"""Формирование, атомарная запись и консольный просмотр отчёта."""
from __future__ import annotations

import json
import tempfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .ai.base import AIProvider
from .fetcher import FetchResult


def build_report(
    entries: list[dict[str, Any]],
    *,
    mode: str,
    provider: AIProvider,
    source: str,
    ai_errors: list[str] | None = None,
    fetch_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    unique: dict[str, dict[str, Any]] = {}
    duplicates = 0
    for entry in entries:
        vacancy_id = str(entry["id"]) if entry.get("id") is not None else ""
        if not vacancy_id:
            continue
        if vacancy_id in unique:
            duplicates += 1
            continue
        unique[vacancy_id] = {
            "id": entry["id"],
            "url": entry.get("url") or None,
            "findings": entry.get("findings", []),
            **{key: entry[key] for key in ("title", "employer") if entry.get(key)},
        }

    items = list(unique.values())
    findings_total = sum(len(item["findings"]) for item in items)
    kinds: Counter[str] = Counter(
        finding.get("kind", "unknown") for item in items for finding in item["findings"]
    )
    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode,
        "source": source,
        "ai": {"provider": provider.name, "model": provider.model},
        "stats": {
            "vacancies_in": len(entries),
            "vacancies_in_report": len(items),
            "duplicates_skipped": duplicates,
            "vacancies_with_findings": sum(1 for item in items if item["findings"]),
            "findings_total": findings_total,
            "by_kind": dict(kinds),
            "ai_errors": len(ai_errors or []),
            "ai_findings": sum(f.get("origin") == "ai" for item in items for f in item["findings"]),
        },
        "vacancies": items,
    }
    if ai_errors:
        report["ai_error_samples"] = ai_errors[:10]
    if fetch_info:
        report["fetch"] = fetch_info
    return report


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with open(fd, "w", encoding="utf-8") as out:
            json.dump(payload, out, ensure_ascii=False, indent=2)
            out.write("\n")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def save_success(report: dict[str, Any], path: Path, last_success: Path | None = None) -> None:
    atomic_write_json(path, report)
    if last_success:
        atomic_write_json(last_success, report)


def save_status(status_path: Path, *, source: str, error: str | None = None,
                has_last_success: bool = False) -> None:
    status = {
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "status": "error" if error else "ok",
        "source": source,
    }
    if error:
        status.update(error=error, last_successful_report_kept=has_last_success)
    atomic_write_json(status_path, status)


def fetch_info(result: FetchResult) -> dict[str, Any]:
    return {
        "pages_loaded": result.pages_loaded,
        "total_on_portal": result.total,
        "vacancies_loaded": len(result.vacancies),
    }


_FINDING_KINDS = {
    "omission": "Пропуск",
    "ambiguity": "Неоднозначность",
    "contradiction": "Противоречие",
}
_FINDING_FIELDS = ("kind", "topic", "field", "quote", "issue", "recommendation")
_TERMINAL_CONTROLS = dict.fromkeys((*range(32), *range(127, 160)), None)


def read_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(report, dict) or not isinstance(report.get("vacancies"), list):
        raise ValueError("Ожидался отчёт с массивом vacancies. Укажите результат run или verify.")

    ids = set()
    for vacancy in report["vacancies"]:
        if not isinstance(vacancy, dict) or type(vacancy.get("id")) not in (str, int):
            raise ValueError("Некорректный ID вакансии в отчёте")
        vacancy_id = str(vacancy["id"])
        if not vacancy_id.strip() or vacancy_id in ids:
            raise ValueError(f"Пустой или повторный ID в отчёте: {vacancy_id!r}")
        ids.add(vacancy_id)
        if not isinstance(vacancy.get("findings"), list):
            raise ValueError(f"У вакансии {vacancy_id!r} нет массива findings")
        for finding in vacancy["findings"]:
            if not isinstance(finding, dict) or any(
                not isinstance(finding.get(field), str) for field in _FINDING_FIELDS
            ):
                raise ValueError(f"Неполное замечание у вакансии {vacancy_id!r}")
    return report


def _console_text(value: Any) -> str:
    return str(value).translate(_TERMINAL_CONTROLS)


def format_console_report(
    report: dict[str, Any],
    vacancy_id: str | None = None,
    *,
    with_findings: bool = False,
    demo: bool = False,
) -> str:
    vacancies = report["vacancies"]
    if vacancy_id is not None:
        vacancy = next((item for item in vacancies if str(item["id"]) == vacancy_id), None)
        if vacancy is None:
            raise ValueError(f"Вакансия {vacancy_id!r} не найдена. Запустите report, чтобы увидеть список ID.")
        return _format_vacancy(vacancy, demo=demo)

    findings = [finding for vacancy in vacancies for finding in vacancy["findings"]]
    count = sum(bool(vacancy["findings"]) for vacancy in vacancies)
    ai_count = sum(finding.get("origin") == "ai" for finding in findings)
    label = "Учебный отчёт" if demo else "Отчёт по вакансиям"
    lines = [
        label,
        f"Вакансий: {len(vacancies)} · с замечаниями: {count}",
        f"Замечаний: {len(findings)} · подтверждено ИИ: {ai_count}",
        "",
    ]
    for vacancy in vacancies:
        total = len(vacancy["findings"])
        if with_findings and not total:
            continue
        title = _console_text(vacancy.get("title") or "Вакансия")
        lines.append(f"{_console_text(vacancy['id'])}  {title}  (замечаний: {total})")
    if not vacancies:
        lines.append("В отчёте нет вакансий.")
    elif with_findings and not count:
        lines.append("Вакансий с замечаниями нет.")
    return "\n".join(lines).rstrip()


def _format_vacancy(vacancy: dict[str, Any], *, demo: bool) -> str:
    title = _console_text(vacancy.get("title") or "Вакансия")
    lines = [f"{title} · {_console_text(vacancy['id'])}"]
    if vacancy.get("employer"):
        lines.append(f"Работодатель: {_console_text(vacancy['employer'])}")
    if vacancy.get("url") and not demo:
        lines.append(f"Карточка: {_console_text(vacancy['url'])}")
    if not vacancy["findings"]:
        lines.append("Замечаний нет.")
    for finding in vacancy["findings"]:
        kind = _FINDING_KINDS.get(finding["kind"], finding["kind"])
        origin = " · подтверждено ИИ" if finding.get("origin") == "ai" else ""
        lines.extend((
            "",
            f"{_console_text(finding['topic'].capitalize())} · {_console_text(kind)}{origin}",
            f"  {_console_text(finding['issue'])}",
        ))
        values = finding.get("values")
        fields = finding.get("value_fields")
        if isinstance(values, list) and len(values) == 2 and isinstance(fields, list) and len(fields) == 2:
            for field, value in zip(fields, values):
                lines.append(f"  {_console_text(field)}: «{_console_text(value)}»")
        else:
            evidence = f"«{_console_text(finding['quote'])}»" if finding["quote"] else "сведения отсутствуют"
            lines.append(f"  {_console_text(finding['field'])}: {evidence}")
        lines.append(f"  Вопрос: {_console_text(finding['recommendation'])}")
    return "\n".join(lines)
