import json
import unittest
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path
from tempfile import TemporaryDirectory

from src.config import Config
from src.view import export_html, report_payload


class ReportViewTest(unittest.TestCase):
    def test_default_uses_demo_until_a_working_report_exists(self):
        with TemporaryDirectory() as folder:
            cfg = replace(Config.load(), report_path=Path(folder) / "report.json")
            self.assertTrue(report_payload(cfg)["demo"])
            cfg.report_path.write_text('{"vacancies":[{"id":"old","findings":[]}]}', encoding="utf-8")
            payload = report_payload(cfg)
            self.assertFalse(payload["demo"])
            self.assertEqual(payload["report"]["vacancies"][0]["id"], "old")

    def test_source_failure_is_shown_only_with_the_working_report(self):
        with TemporaryDirectory() as folder:
            base = Path(folder)
            cfg = replace(Config.load(), report_path=base / "report.json", run_status_path=base / "status.json")
            cfg.report_path.write_text('{"vacancies":[]}', encoding="utf-8")
            cfg.run_status_path.write_text(json.dumps({"status": "error"}), encoding="utf-8")
            self.assertTrue(report_payload(cfg)["stale"])
            self.assertFalse(report_payload(cfg, demo=True)["stale"])
            self.assertFalse(report_payload(cfg, explicit_path=cfg.report_path)["stale"])

    def test_explicit_input_must_be_a_report(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            path.write_text('{"results":{"vacancies":[]}}', encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "vacancies"):
                report_payload(Config.load(), explicit_path=path)


    def test_html_export_embeds_report_and_keeps_quotes_as_data(self):
        class EmbeddedReportParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.scripts = []
                self.payload = None
                self.links = []
                self._embedded = False

            def handle_starttag(self, tag, attrs):
                properties = dict(attrs)
                if tag == "script":
                    self.scripts.append(properties)
                    self._embedded = properties.get("id") == "embedded-report"
                elif tag == "link":
                    self.links.append(properties)

            def handle_data(self, data):
                if self._embedded:
                    self.payload = json.loads(data)

            def handle_endtag(self, tag):
                if tag == "script":
                    self._embedded = False

        with TemporaryDirectory() as folder:
            report = Path(folder) / "report.json"
            output = Path(folder) / "report.html"
            title = "Пример с фрагментом </script> из источника"
            report.write_text(json.dumps({"vacancies": [{"id": "1", "title": title, "findings": []}]}))
            export_html(Config.load(), output, report, demo=False)
            parser = EmbeddedReportParser()
            parser.feed(output.read_text(encoding="utf-8"))
        self.assertEqual(parser.payload["report"]["vacancies"][0]["title"], title)
        self.assertEqual(len(parser.scripts), 2)
        self.assertFalse(any("src" in script for script in parser.scripts))
        self.assertEqual(parser.links, [])
