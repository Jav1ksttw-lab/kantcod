"""Формирование, дедупликация и атомарная запись отчёта."""
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
        vacancy_id = str(entry.get("id") or "")
        if not vacancy_id:
            continue
        if vacancy_id in unique:
            duplicates += 1
            continue
        unique[vacancy_id] = {
            "id": entry["id"],
            "url": entry.get("url") or None,
            "findings": entry.get("findings", []),
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


def save_failure(status_path: Path, message: str, *, source: str) -> None:
    """При ошибке источника последний успешный отчёт НЕ перезаписывается."""
    atomic_write_json(
        status_path,
        {
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "status": "error",
            "source": source,
            "error": message,
            "last_successful_report_kept": True,
        },
    )


def fetch_info(result: FetchResult) -> dict[str, Any]:
    return {
        "pages_loaded": result.pages_loaded,
        "total_on_portal": result.total,
        "vacancies_loaded": len(result.vacancies),
    }
