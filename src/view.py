"""Показывает сохранённый отчёт в браузере на этом компьютере."""
from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .config import Config, ROOT

ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
DEMO_REPORT = ROOT / "data" / "reports" / "report_example.json"


def report_payload(cfg: Config, explicit_path: Path | None = None, *, demo: bool = False) -> dict:
    demo = demo or (explicit_path is None and not cfg.report_path.is_file())
    path = DEMO_REPORT if demo else explicit_path or cfg.report_path
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or not isinstance(report.get("vacancies"), list):
        raise ValueError("В файле нет массива vacancies. Укажите JSON-отчёт проекта.")
    stale = False
    if not demo and explicit_path is None and cfg.run_status_path.is_file():
        try:
            status = json.loads(cfg.run_status_path.read_text(encoding="utf-8"))
            stale = isinstance(status, dict) and status.get("status") == "error"
        except (OSError, ValueError):
            pass
    return {"report": report, "demo": demo, "stale": stale}


def serve_report(cfg: Config, report_path: Path | None, demo: bool, port: int) -> None:
    assets = Path(__file__).with_name("web")

    class ReportHandler(BaseHTTPRequestHandler):
        def _send(self, body: bytes, content_type: str, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
            )
            self.end_headers()
            if self.command == "GET":
                self.wfile.write(body)

        def do_GET(self) -> None:
            path = self.path.split("?", 1)[0]
            if path == "/api/report":
                try:
                    payload = report_payload(cfg, report_path, demo=demo)
                    status = HTTPStatus.OK
                except (OSError, ValueError):
                    payload = {"error": "Не удалось прочитать отчёт. Загрузите готовый JSON."}
                    status = HTTPStatus.UNPROCESSABLE_ENTITY
                self._send(json.dumps(payload, ensure_ascii=False).encode(), "application/json", status)
            elif path in ASSETS:
                filename, content_type = ASSETS[path]
                self._send((assets / filename).read_bytes(), content_type)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        do_HEAD = do_GET

    with ThreadingHTTPServer(("127.0.0.1", port), ReportHandler) as server:
        print(f"Просмотр отчёта: http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()
