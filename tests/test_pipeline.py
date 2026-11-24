import json
import unittest
from pathlib import Path
from unittest.mock import patch

from src.analyzer import analyze_one, parse_model_response
from src.ai.base import AIProvider
from src.config import ROOT, Config
from src.facts import build_facts, rule_findings
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
        good = json.dumps({"findings": [{
            "kind": "ambiguity", "topic": "график работы", "source_field": "schedule",
            "quote": "Гибкий график", "issue": "Не ясны дни и смены",
            "recommendation": "Уточните дни недели и время начала и окончания смены",
        }]}, ensure_ascii=False)
        entry, error = analyze_one(self.by_id("train-001"), FakeProvider(good), self.cfg)
        self.assertIsNone(error)
        self.assertTrue(any(f["topic"] == "график работы" and f["quote"] == "Гибкий график" for f in entry["findings"]))

        bad = json.dumps({"findings": [{
            "kind": "ambiguity", "topic": "график работы", "source_field": "schedule",
            "quote": "Ежедневно с 8 до 17", "issue": "Нет сведений", "recommendation": "Добавьте",
        }]}, ensure_ascii=False)
        entry, _ = analyze_one(self.by_id("train-001"), FakeProvider(bad), self.cfg)
        self.assertEqual(entry["findings"], [])

    def test_parse_markdown_response(self):
        parsed = parse_model_response('```json\n{"findings": [{"kind": "ambiguity"}]}\n```')
        self.assertEqual(parsed, [{"kind": "ambiguity"}])

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
                {"vacancy": {"id": f"v{offset + i}", "job-name": "Тест"}} for i in range(2)
            ]
            return FakeResponse({"meta": {"total": 100}, "results": {"vacancies": vacancies}})

        from dataclasses import replace
        cfg = replace(self.cfg, page_size=2, max_pages=2, max_vacancies=10)
        with patch("src.fetcher.requests.get", side_effect=fake_get):
            result = fetch_vacancies(cfg)
        self.assertEqual(len(result.vacancies), 4)
        self.assertEqual(result.pages_loaded, 2)
        self.assertTrue(any("offset=0" in url for url in calls))
        self.assertTrue(any("offset=2" in url for url in calls))


if __name__ == "__main__":
    unittest.main()
