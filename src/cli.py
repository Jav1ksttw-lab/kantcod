"""Точка входа: python -m src.cli {run|verify|schedule|report|check|resume}."""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter
from filelock import FileLock, Timeout

from .ai.base import AIUnavailable
from .ai.factory import create_provider
from .analyzer import analyze_all
from .config import ROOT, Config
from .fetcher import FetchError, extract_vacancies, fetch_vacancies
from .report import (
    atomic_write_json, build_report, fetch_info, format_console_report, read_report, save_status, save_success,
)
from .resume import draft_resume, find_vacancy, load_vacancies

EXIT_ERROR = 1
DEMO_REPORT = ROOT / "data" / "reports" / "report_example.json"


def _summary(report: dict[str, Any]) -> str:
    stats = report["stats"]
    return (
        f"Вакансий в отчёте: {stats['vacancies_in_report']} "
        f"(дубликатов пропущено: {stats['duplicates_skipped']}); "
        f"замечаний: {stats['findings_total']}; "
        f"из них замечаний ИИ: {stats['ai_findings']}, "
        f"ошибок ИИ: {stats['ai_errors']}; "
        f"провайдер: {report['ai']['provider']}/{report['ai']['model']}"
    )


def _load_input(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8-sig") as handle:
        return extract_vacancies(json.load(handle))


def _analyze(
    vacancies: list[dict[str, Any]],
    args: argparse.Namespace,
    cfg: Config,
    *,
    mode: str,
    source: str,
    fetch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = create_provider(cfg, args.ai, strict=args.strict_ai)
    entries, ai_errors = analyze_all(vacancies, provider, cfg)
    if ai_errors:
        print(f"[WARN] Пример ошибки ИИ: {ai_errors[0]}", file=sys.stderr)
        unique_count = len({str(vacancy["id"]) for vacancy in vacancies})
        if args.strict_ai or len(ai_errors) == unique_count:
            raise AIUnavailable(f"Ошибки ИИ у {len(ai_errors)} из {unique_count} вакансий")
    return build_report(
        entries, mode=mode, provider=provider, source=source, ai_errors=ai_errors, fetch_info=fetch,
    )


def cmd_run(args: argparse.Namespace, cfg: Config) -> int:
    cfg.run_status_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = cfg.run_status_path.with_suffix(".lock")
    try:
        with FileLock(lock_path, timeout=0):
            return _run_locked(args, cfg)
    except Timeout:
        print("[ERROR] Другой запуск уже формирует отчёт.", file=sys.stderr)
        return EXIT_ERROR


def _run_locked(args: argparse.Namespace, cfg: Config) -> int:
    if args.max is not None:
        cfg = replace(cfg, max_vacancies=args.max)
    if args.pages is not None:
        cfg = replace(cfg, max_pages=args.pages)
    output = Path(args.output) if args.output else cfg.report_path
    if output.resolve() in {path.resolve() for path in (
        cfg.run_status_path, cfg.last_input_path, cfg.last_success_path, cfg.run_status_path.with_suffix(".lock"),
    )}:
        raise ValueError("Путь отчёта совпадает со служебным файлом")
    try:
        fetched = fetch_vacancies(cfg)
        report = _analyze(
            fetched.vacancies, args, cfg,
            mode="scheduled" if args.command == "schedule" or args.scheduled else "manual",
            source=fetched.source_url, fetch=fetch_info(fetched),
        )
        atomic_write_json(cfg.last_input_path, {"results": {"vacancies": [{"vacancy": v} for v in fetched.vacancies]}})
        save_success(report, output, cfg.last_success_path)
    except (FetchError, AIUnavailable, OSError) as exc:
        message = f"Источник недоступен: {exc}" if isinstance(exc, FetchError) else str(exc)
        print(f"[ERROR] {message}", file=sys.stderr)
        save_status(cfg.run_status_path, source=cfg.source_url, error=message,
                    has_last_success=cfg.last_success_path.is_file())
        return EXIT_ERROR
    save_status(cfg.run_status_path, source=cfg.source_url)
    print(f"[OK] Сохранено: {output}")
    print(f"Страниц API: {fetched.pages_loaded}")
    print(_summary(report))
    return 0


def cmd_verify(args: argparse.Namespace, cfg: Config) -> int:
    input_path = Path(args.input) if args.input else cfg.sample_input
    vacancies = _load_input(input_path)
    if args.max is not None:
        vacancies = vacancies[: args.max]
    output = Path(args.output) if args.output else cfg.sample_report
    if output.resolve() == input_path.resolve():
        raise ValueError("Пути входного JSON и отчёта должны отличаться")
    report = _analyze(vacancies, args, cfg, mode="verify", source=str(input_path))
    save_success(report, output)
    print(f"[OK] Сохранено: {output}")
    print(_summary(report))
    return 0


def cmd_schedule(args: argparse.Namespace, cfg: Config) -> int:
    tz = ZoneInfo(cfg.timezone)
    if not croniter.is_valid(cfg.schedule):
        raise ValueError(f"Некорректное cron-расписание: {cfg.schedule}")
    print(f"[INFO] Расписание: {cfg.schedule} ({cfg.timezone}), источник: {cfg.source_url}", flush=True)

    if args.now:
        cmd_run(args, cfg)

    while True:
        next_run = croniter(cfg.schedule, datetime.now(tz)).get_next(datetime)
        print(f"[INFO] Следующий запуск: {next_run.isoformat(timespec='seconds')}", flush=True)
        time.sleep(max(1.0, next_run.timestamp() - time.time()))
        cmd_run(args, cfg)


def cmd_check(args: argparse.Namespace, cfg: Config) -> int:
    """Локальная самопроверка без сети и без ключей."""
    vacancies = _load_input(cfg.sample_input)
    provider = create_provider(cfg, "rules")
    entries, errors = analyze_all(vacancies, provider, cfg)
    report = build_report(entries, mode="check", provider=provider, source=str(cfg.sample_input), ai_errors=errors)
    with TemporaryDirectory() as temporary:
        temp_path = Path(temporary) / "report.json"
        save_success(report, temp_path)
        data = read_report(temp_path)
    if len(data["vacancies"]) != len({str(v["id"]) for v in vacancies}):
        raise ValueError("Самопроверка выявила пропущенные или повторные ID")
    print(f"[OK] Самопроверка пройдена: {_summary(report)}")
    return 0


def cmd_resume(args: argparse.Namespace, cfg: Config) -> int:
    provider = create_provider(cfg, args.ai, strict=True)
    vacancies = load_vacancies(args.input, cfg)
    vacancy = find_vacancy(vacancies, args.vacancy_id)
    resume_path = Path(args.resume) if args.resume else cfg.resume_path
    resume = json.loads(resume_path.read_text(encoding="utf-8-sig"))
    draft = draft_resume(vacancy, resume, provider, cfg)
    output = Path(args.output) if args.output else cfg.resume_draft_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(draft.rstrip() + "\n", encoding="utf-8")
    print(f"[OK] Черновик резюме сохранён: {output}")
    return 0


def cmd_report(args: argparse.Namespace, cfg: Config) -> int:
    sample = args.demo or (args.file is None and not cfg.report_path.is_file())
    path = DEMO_REPORT if sample else args.file or cfg.report_path
    report = read_report(path)
    print(format_console_report(report, args.id, with_findings=args.with_findings, demo=sample))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description="Прозрачная вакансия")
    parser.add_argument("--config", help="Путь к config.json")
    sub = parser.add_subparsers(dest="command", required=True)

    def positive_int(value: str) -> int:
        number = int(value)
        if number <= 0:
            raise argparse.ArgumentTypeError("значение должно быть положительным")
        return number

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--ai", choices=("auto", "gigachat", "ollama", "llamacpp", "rules"), help="переопределить провайдера ИИ")

    run = sub.add_parser("run", help="получить вакансии через API и сохранить отчёт")
    add_common(run)
    run.add_argument("--strict-ai", action="store_true")
    run.add_argument("--max", type=positive_int, help="максимум вакансий")
    run.add_argument("--pages", type=positive_int, help="максимум страниц")
    run.add_argument("--output", help="путь отчёта")
    run.add_argument("--now", action="store_true", help=argparse.SUPPRESS)
    run.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    run.set_defaults(func=cmd_run)

    verify = sub.add_parser("verify", help="проанализировать локальный JSON без обращения к порталу")
    add_common(verify)
    verify.add_argument("--input", help="JSON в формате ответа API")
    verify.add_argument("--output", help="путь отчёта")
    verify.add_argument("--max", type=positive_int, help="ограничить число вакансий")
    verify.add_argument("--strict-ai", action="store_true", help="прекратить работу при любой ошибке ИИ")
    verify.set_defaults(func=cmd_verify)

    sched = sub.add_parser("schedule", help="запускать отчёт по расписанию из config.json")
    add_common(sched)
    sched.add_argument("--strict-ai", action="store_true")
    sched.add_argument("--max", type=positive_int)
    sched.add_argument("--pages", type=positive_int)
    sched.add_argument("--output")
    sched.add_argument("--now", action="store_true", help="сразу выполнить первый запуск")
    sched.set_defaults(func=cmd_schedule)

    check = sub.add_parser("check", help="самопроверка формата без сети и ИИ")
    check.set_defaults(func=cmd_check)

    resume = sub.add_parser("resume", help="доп. сценарий: черновик резюме под вакансию")
    add_common(resume)
    resume.add_argument("--vacancy-id", required=True)
    resume.add_argument("--input", help="JSON с вакансиями (по умолчанию последняя загрузка)")
    resume.add_argument("--resume", help="исходное резюме JSON (вымышленное)")
    resume.add_argument("--output")
    resume.set_defaults(func=cmd_resume)

    report = sub.add_parser("report", help="показать сохранённый отчёт в терминале")
    source = report.add_mutually_exclusive_group()
    source.add_argument("--demo", action="store_true", help="показать учебный отчёт")
    source.add_argument("--file", type=Path, help="путь к готовому JSON-отчёту")
    scope = report.add_mutually_exclusive_group()
    scope.add_argument("--id", help="показать замечания к одной вакансии")
    scope.add_argument("--with-findings", action="store_true", help="показать только вакансии с замечаниями")
    report.set_defaults(func=cmd_report)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args, Config.load(args.config))
    except (OSError, ValueError, AIUnavailable, KeyError) as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
