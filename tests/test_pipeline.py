import json
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from dataclasses import replace
from tempfile import TemporaryDirectory
import unittest
from pathlib import Path
from unittest.mock import patch

from src.analyzer import analyze_one, parse_model_response
from src.ai.base import AIProvider
from src.cli import main
from src.config import ROOT, Config
from src.facts import ambiguity_candidates, build_facts, rule_findings
from src.report import build_report
from src.fetcher import fetch_vacancies


class FakeProvider(AIProvider):
    name = "fake"
    model = "test"

    def __init__(self, answer='{"findings": []}'):
        self.answer = answer

    def complete(self, system, user):
        return self.answer


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def sample_vacancies():
    payload = json.loads((ROOT / "data/sample/training_vacancies.json").read_text(encoding="utf-8"))
    return [item["vacancy"] for item in payload["results"]["vacancies"]]


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = Config.load()
        cls.vacancies = sample_vacancies()

    def by_id(self, vacancy_id):
        return next(v for v in self.vacancies if v["id"] == vacancy_id)

    def test_rule_omissions(self):
        findings = rule_findings(self.by_id("train-002"), build_facts(self.by_id("train-002")))
        fields = {f["field"] for f in findings}
        self.assertTrue({"duty", "requirements", "salary", "employment"} <= fields)
        self.assertTrue(all(f["kind"] == "omission" and f["quote"] == "" for f in findings))

    def test_rule_contradictions(self):
        vacancy = self.by_id("train-003")
        findings = rule_findings(vacancy, build_facts(vacancy))
        contradictions = [f for f in findings if f["kind"] == "contradiction"]
        self.assertEqual(len(contradictions), 2)
        self.assertTrue(all(len(f["values"]) == 2 for f in contradictions))

    def test_no_repeat_requirement_in_description_is_not_a_problem(self):
        vacancy = self.by_id("train-004")
        findings = rule_findings(vacancy, build_facts(vacancy))
        self.assertEqual(findings, [])

    def test_ai_finding_is_validated(self):
        vacancy = self.by_id("train-001")
        entry, error = analyze_one(vacancy, FakeProvider('{"findings":[1,1]}'), self.cfg)
        self.assertIsNone(error)
        self.assertEqual(len(entry["findings"]), 1)
        self.assertEqual(entry["findings"][0]["quote"], "Гибкий график")
        self.assertEqual(entry["findings"][0]["origin"], "ai")

        entry, error = analyze_one(vacancy, FakeProvider('{"findings":[99]}'), self.cfg)
        self.assertIsNotNone(error)
        self.assertEqual(entry["findings"], [])

    def test_flexible_schedule_with_hours_still_needs_workdays(self):
        vacancy = {**self.by_id("train-001"), "schedule": "Гибкий график, с 09:00 до 18:00"}
        findings = ambiguity_candidates(build_facts(vacancy))
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["quote"], "Гибкий график")
        self.assertIn("В какие дни", findings[0]["recommendation"])
        self.assertNotIn("часы", findings[0]["recommendation"])

    def test_flexible_schedule_with_workdays_still_needs_hours(self):
        vacancy = {**self.by_id("train-001"), "schedule": "Гибкий график по будням"}
        findings = ambiguity_candidates(build_facts(vacancy))
        self.assertEqual(len(findings), 1)
        self.assertIn("Во сколько", findings[0]["recommendation"])

    def test_workdays_in_another_field_complete_the_flexible_schedule(self):
        vacancy = {
            **self.by_id("train-001"),
            "schedule": "Гибкий график, с 09:00 до 18:00",
            "conditions": "Рабочие дни: пн–пт.",
        }
        self.assertEqual(ambiguity_candidates(build_facts(vacancy)), [])

    def test_parse_markdown_response(self):
        self.assertEqual(parse_model_response('```json\n{"findings": [1]}\n```', 1), [1])

    def test_report_dedupes_by_id(self):
        entries = [{"id": "a", "url": "u", "findings": []}, {"id": "a", "url": "u", "findings": []}]
        report = build_report(entries, mode="verify", provider=FakeProvider(), source="test")
        self.assertEqual(report["stats"]["vacancies_in_report"], 1)
        self.assertEqual(report["stats"]["duplicates_skipped"], 1)

    def test_fetch_two_pages(self):
        calls = []

        def fake_get(url, **kwargs):
            calls.append(url)
            offset = int(url.split("offset=")[-1].split("&")[0])
            vacancies = [
                {"vacancy": {"id": f"v{offset * 2 + i}", "job-name": "Тест"}} for i in range(2)
            ]
            return FakeResponse({"meta": {"total": 100}, "results": {"vacancies": vacancies}})

        cfg = replace(self.cfg, page_size=2, max_pages=2, max_vacancies=10)
        with patch("src.fetcher.requests.get", side_effect=fake_get):
            result = fetch_vacancies(cfg)
        self.assertEqual(len(result.vacancies), 4)
        self.assertEqual(result.pages_loaded, 2)
        self.assertTrue(any("offset=0" in url for url in calls))
        self.assertTrue(any("offset=1" in url for url in calls))

    def test_structured_and_descriptive_fields_supply_missing_details(self):
        vacancy = self.by_id("train-004").copy()
        vacancy.update({
            "schedule": "",
            "employment": "",
            "salary": "",
            "salary_min": 0,
            "salary_max": 70000,
            "requirements": "",
            "qualification": "Полная занятость. График 5/2. Высшее образование.",
            "addresses": {},
            "conditions": "Место работы: ул. Садовая, 4.",
        })
        self.assertEqual(rule_findings(vacancy, build_facts(vacancy)), [])

    def test_contradiction_cites_both_source_fields(self):
        vacancy = self.by_id("train-003")
        facts = build_facts(vacancy)
        for finding in rule_findings(vacancy, facts):
            if finding["kind"] == "contradiction":
                for field, value in zip(finding["value_fields"], finding["values"]):
                    self.assertIn(value, facts[field])

    def test_strict_ai_rejects_partial_invalid_response(self):
        provider = FakeProvider()
        answers = ['{"findings": []}', "невалидный JSON"]
        with TemporaryDirectory() as temp, patch.object(provider, "complete", side_effect=answers), patch(
            "src.cli.create_provider", return_value=provider,
        ):
            output = Path(temp) / "report.json"
            output.write_text("previous", encoding="utf-8")
            self.assertEqual(main(["verify", "--strict-ai", "--output", str(output)]), 1)
            self.assertEqual(output.read_text(encoding="utf-8"), "previous")

    def test_verify_checks_duplicate_id_once_and_accepts_utf8_bom(self):
        vacancy = self.by_id("train-001")
        provider = FakeProvider('{"findings":[1]}')
        with TemporaryDirectory() as temp, patch(
            "src.cli.create_provider", return_value=provider,
        ), patch.object(provider, "complete", wraps=provider.complete) as complete, redirect_stdout(StringIO()):
            source = Path(temp) / "vacancies.json"
            output = Path(temp) / "report.json"
            source.write_text(json.dumps([vacancy, vacancy]), encoding="utf-8-sig")
            self.assertEqual(main(["verify", "--strict-ai", "--input", str(source), "--output", str(output)]), 0)
            complete.assert_called_once()
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["stats"]["vacancies_in"], 2)
            self.assertEqual(report["stats"]["duplicates_skipped"], 1)
            self.assertEqual(len(report["vacancies"]), 1)

    def test_console_report_shows_citations_and_recommendation(self):
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(main(["report", "--demo", "--id", "train-003"]), 0)
        self.assertIn("salary: «до 30 000»", output.getvalue())
        self.assertIn("salary_min: «40000»", output.getvalue())
        self.assertIn("Вопрос: Какой диапазон оплаты", output.getvalue())

    def test_console_report_filters_clean_vacancies(self):
        with redirect_stdout(StringIO()) as output:
            self.assertEqual(main(["report", "--demo", "--with-findings"]), 0)
        self.assertIn("train-001", output.getvalue())
        self.assertNotIn("train-004", output.getvalue())

    def test_console_report_rejects_input_vacancies_file(self):
        with redirect_stderr(StringIO()) as error:
            self.assertEqual(main(["report", "--file", str(self.cfg.sample_input)]), 1)
        self.assertIn("Укажите результат run или verify", error.getvalue())

    def test_source_failure_preserves_working_report(self):
        with TemporaryDirectory() as temp:
            folder = Path(temp)
            cfg = replace(
                self.cfg, report_path=folder / "report.json", last_success_path=folder / "previous.json",
                run_status_path=folder / "status.json", last_input_path=folder / "input.json", retries=1,
            )
            for path in (cfg.report_path, cfg.last_success_path):
                path.write_text("previous", encoding="utf-8")
            responses = [
                FakeResponse({"results": {"vacancies": [{"vacancy": {"id": "first"}}]}}),
                FakeResponse({"status": 500, "results": {"vacancies": []}}),
            ]
            with patch("src.cli.Config.load", return_value=cfg), patch("src.fetcher.requests.get", side_effect=responses):
                self.assertEqual(main(["run", "--ai", "rules"]), 1)
            self.assertEqual(cfg.report_path.read_text(encoding="utf-8"), "previous")
            self.assertEqual(cfg.last_success_path.read_text(encoding="utf-8"), "previous")
            status = json.loads(cfg.run_status_path.read_text(encoding="utf-8"))
            self.assertEqual(status["status"], "error")
            self.assertTrue(status["last_successful_report_kept"])


if __name__ == "__main__":
    unittest.main()
