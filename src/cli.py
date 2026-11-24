"""Точка входа: python -m src.cli {run|verify|schedule|check|resume}."""
from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

from croniter import croniter

from .ai.base import AIUnavailable
from .ai.factory import create_provider
from .analyzer import analyze_all
from .config import Config
from .fetcher import FetchError, extract_vacancies, fetch_vacancies
from .report import atomic_write_json, build_report, fetch_info, save_failure, save_success
from .resume import draft_resume, find_vacancy, load_vacancies

EXIT_ERROR = 1


def _summary(report: dict[str, Any]) -> str:
    stats = report["stats"]
    return (
        f"Вакансий в отчёте: {stats['vacancies_in_report']} "
        f"(дубликатов пропущено: {stats['duplicates_skipped']}); "
        f"замечаний: {stats['findings_total']}; "
        f"ошибок ИИ: {stats['ai_errors']}; "
        f"провайдер: {report['ai']['provider']}/{report['ai']['model']}"
    )


def _make_provider(cfg: Config, ai_override: str | None, strict: bool = False):
    try:
        return create_provider(cfg, ai_override, strict=strict)
    except AIUnavailable as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        raise SystemExit(EXIT_ERROR) from exc


def _load_input(path: Path) -> list[dict[str, Any]]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    vacancies = extract_vacancies(payload)
    if not vacancies:
        raise ValueError(f"В файле {path} нет вакансий в формате ответа API")
    return vacancies


def cmd_run(args: argparse.Namespace, cfg: Config) -> int:
    if args.max is not None:
        cfg = replace(cfg, max_vacancies=args.max)
    if args.pages is not None:
        cfg = replace(cfg, max_pages=args.pages)
    provider = _make_provider(cfg, args.ai)
    try:
        fetched = fetch_vacancies(cfg)
    except FetchError as exc:
        message = f"Источник недоступен: {exc}"
        print(f"[ERROR] {message}", file=sys.stderr)
        save_failure(cfg.run_status_path, message, source=cfg.source_url)
        print("[INFO] Последний успешный отчёт оставлен без изменений.", file=sys.stderr)
        return EXIT_ERROR

    atomic_write_json(cfg.last_input_path, {"results": {"vacancies": [{"vacancy": v} for v in fetched.vacancies]}})
    entries, ai_errors = analyze_all(fetched.vacancies, provider, cfg)
    report = build_report(
        entries,
        mode="scheduled" if getattr(args, "scheduled", False) else "manual",
        provider=provider,
        source=fetched.source_url,
        ai_errors=ai_errors,
        fetch_info=fetch_info(fetched),
    )
    output = Path(args.output) if args.output else cfg.report_path
    save_success(report, output, cfg.last_success_path)
    print(f"[OK] Отчёт сохранён: {output}")
    print(_summary(report))
    if ai_errors:
        print(f"[WARN] Пример ошибки ИИ: {ai_errors[0]}", file=sys.stderr)
    return 0


def cmd_verify(args: argparse.Namespace, cfg: Config) -> int:
    provider = _make_provider(cfg, args.ai, strict=args.strict_ai)
    input_path = Path(args.input) if args.input else cfg.sample_input
    vacancies = _load_input(input_path)
    if args.max is not None:
        vacancies = vacancies[: args.max]
    entries, ai_errors = analyze_all(vacancies, provider, cfg)
    report = build_report(
        entries,
        mode="verify",
        provider=provider,
        source=str(input_path),
        ai_errors=ai_errors,
    )
    output = Path(args.output) if args.output else cfg.sample_report
    save_success(report, output)
    print(f"[OK] Проверочный отчёт сохранён: {output}")
    print(_summary(report))
    if ai_errors:
        print(f"[WARN] Пример ошибки ИИ: {ai_errors[0]}", file=sys.stderr)
        if args.strict_ai and len(ai_errors) == len(vacancies):
            print("[ERROR] Ни один запрос к ИИ не выполнен (--strict-ai).", file=sys.stderr)
            return EXIT_ERROR
    return 0


def cmd_schedule(args: argparse.Namespace, cfg: Config) -> int:
    provider = _make_provider(cfg, args.ai)
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(cfg.timezone)
    except Exception:
        tz = None
    print(f"[INFO] Расписание: {cfg.schedule} ({cfg.timezone}), источник: {cfg.source_url}")

    if args.now:
        print("[INFO] Стартовый запуск...")
        cmd_run(args, cfg)

    while True:
        now = datetime.now(tz)
        next_run = croniter(cfg.schedule, now).get_next(datetime)
        print(f"[INFO] Следующий запуск: {next_run.isoformat(timespec='seconds')}")
        time.sleep(max(1.0, (next_run - datetime.now(tz)).total_seconds()))
        try:
            cmd_run(args, cfg)
        except Exception as exc:  # планировщик не должен падать из-за одного неудачного запуска
            message = f"Ошибка запланированного запуска: {exc}"
            print(f"[ERROR] {message}", file=sys.stderr)
            save_failure(cfg.run_status_path, message, source=cfg.source_url)


def cmd_check(args: argparse.Namespace, cfg: Config) -> int:
    """Локальная самопроверка без сети и без ключей."""
    vacancies = _load_input(cfg.sample_input)
    provider = create_provider(cfg, "rules")
    entries, errors = analyze_all(vacancies, provider, cfg)
    report = build_report(entries, mode="check", provider=provider, source=str(cfg.sample_input), ai_errors=errors)
    temp_path = cfg.report_path.parent / "_selftest.json"
    save_success(report, temp_path)
    data = json.loads(temp_path.read_text(encoding="utf-8"))
    temp_path.unlink()
    assert len(data["vacancies"]) == len({str(v.get("id")) for v in vacancies}), "дубликаты ID"
    assert all(set(("id", "url", "findings")) <= set(item) for item in data["vacancies"]), "схема нарушена"
    assert all(
        set(("kind", "topic", "field", "quote", "issue", "recommendation")) <= set(f)
        for item in data["vacancies"]
        for f in item["findings"]
    ), "схема замечания нарушена"
    print(f"[OK] Самопроверка пройдена: {_summary(report)}")
    return 0


def cmd_resume(args: argparse.Namespace, cfg: Config) -> int:
    provider = _make_provider(cfg, args.ai, strict=True)
    vacancies = load_vacancies(args.input or str(cfg.last_input_path))
    vacancy = find_vacancy(vacancies, args.vacancy_id)
    resume_path = Path(args.resume) if args.resume else cfg.resume_path
    resume = json.loads(resume_path.read_text(encoding="utf-8"))
    draft = draft_resume(vacancy, resume, provider, cfg)
    output = Path(args.output) if args.output else cfg.resume_draft_path
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(draft.rstrip() + "\n", encoding="utf-8")
    print(f"[OK] Черновик резюме сохранён: {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m src.cli", description="Прозрачная вакансия")
    parser.add_argument("--config", help="Путь к config.json")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--ai", choices=("auto", "gigachat", "ollama", "rules"), help="переопределить провайдера ИИ")

    run = sub.add_parser("run", help="получить вакансии через API и сохранить отчёт")
    add_common(run)
    run.add_argument("--max", type=int, help="максимум вакансий")
    run.add_argument("--pages", type=int, help="максимум страниц")
    run.add_argument("--output", help="путь отчёта")
    run.add_argument("--now", action="store_true", help=argparse.SUPPRESS)
    run.add_argument("--scheduled", action="store_true", help=argparse.SUPPRESS)
    run.set_defaults(func=cmd_run)

    verify = sub.add_parser("verify", help="проанализировать локальный JSON без обращения к порталу")
    add_common(verify)
    verify.add_argument("--input", help="JSON в формате ответа API")
    verify.add_argument("--output", help="путь отчёта")
    verify.add_argument("--max", type=int, help="ограничить число вакансий")
    verify.add_argument("--strict-ai", action="store_true", help="прекратить работу, если ИИ не настроен")
    verify.set_defaults(func=cmd_verify)

    sched = sub.add_parser("schedule", help="запускать отчёт по расписанию из config.json")
    add_common(sched)
    sched.add_argument("--max", type=int)
    sched.add_argument("--pages", type=int)
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    cfg = Config.load(args.config)
    return args.func(args, cfg)


if __name__ == "__main__":
    raise SystemExit(main())
