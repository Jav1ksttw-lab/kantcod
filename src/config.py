"""Загрузка конфигурации. Секреты читаются только из окружения / .env."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = ROOT / "config" / "config.json"


@dataclass(frozen=True)
class Config:
    source_url: str
    schedule: str
    timezone: str
    max_vacancies: int
    page_size: int
    max_pages: int
    request_timeout: int
    retries: int
    retry_backoff_seconds: float
    ai_provider: str
    ai_workers: int
    temperature: float
    max_chars_per_field: int
    gigachat_model: str
    ollama_model: str
    ollama_url: str
    report_path: Path
    last_success_path: Path
    run_status_path: Path
    last_input_path: Path
    sample_input: Path
    sample_report: Path
    resume_path: Path
    resume_draft_path: Path

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        load_dotenv(ROOT / ".env")
        cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
        raw: dict[str, Any] = json.loads(cfg_path.read_text(encoding="utf-8"))
        ai = raw.get("ai", {})
        paths = raw.get("paths", {})

        def env(name: str, default: str | None = None) -> str | None:
            return os.getenv(name) if os.getenv(name) not in (None, "") else default

        def path_value(key: str, default: str) -> Path:
            value = Path(paths.get(key, default))
            return value if value.is_absolute() else ROOT / value

        def int_env(name: str, default: int) -> int:
            return int(env(name, str(default)) or default)

        return cls(
            source_url=env("VACANCY_SOURCE_URL", raw["source_url"]),
            schedule=env("VACANCY_SCHEDULE", raw["schedule"]),
            timezone=raw.get("timezone", "Europe/Kaliningrad"),
            max_vacancies=int_env("VACANCY_MAX", raw.get("max_vacancies", 50)),
            page_size=int(raw.get("page_size", 25)),
            max_pages=int(raw.get("max_pages", 2)),
            request_timeout=int(raw.get("request_timeout", 20)),
            retries=int(raw.get("retries", 3)),
            retry_backoff_seconds=float(raw.get("retry_backoff_seconds", 1.0)),
            ai_provider=env("AI_PROVIDER", ai.get("provider", "auto")),
            ai_workers=int(ai.get("workers", 4)),
            temperature=float(ai.get("temperature", 0.1)),
            max_chars_per_field=int(ai.get("max_chars_per_field", 1200)),
            gigachat_model=env("GIGACHAT_MODEL", ai.get("gigachat_model", "GigaChat")),
            ollama_model=env("OLLAMA_MODEL", ai.get("ollama_model", "qwen2.5:3b")),
            ollama_url=env("OLLAMA_URL", ai.get("ollama_url", "http://localhost:11434")),
            report_path=path_value("report", "data/reports/report.json"),
            last_success_path=path_value("last_success", "data/reports/report.last_success.json"),
            run_status_path=path_value("run_status", "data/reports/last_run.json"),
            last_input_path=path_value("last_input", "data/reports/last_input.json"),
            sample_input=path_value("sample_input", "data/sample/training_vacancies.json"),
            sample_report=path_value("sample_report", "data/reports/report_example.json"),
            resume_path=path_value("resume", "data/sample/resume.json"),
            resume_draft_path=path_value("resume_draft", "data/reports/resume_draft.md"),
        )
