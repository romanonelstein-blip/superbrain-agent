import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LiveProviderGateTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location(
            "validate_live_provider", ROOT / "scripts" / "validate_live_provider.py"
        )
        self.gate = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.gate)

    def report(self, **overrides):
        row = dict(provider="openai", model="test-model", attempted=True, success=True)
        row.update(overrides)
        return dict(liveSmoke="completed", results=[row])

    def test_accepts_completed_real_provider_result(self):
        self.assertTrue(self.gate.validate(self.report()))

    def test_rejects_skipped_missing_or_empty_results(self):
        for report in ({}, {"liveSmoke": "skipped"},
                       {"liveSmoke": "completed", "results": []},
                       {"liveSmoke": "completed", "results": None}):
            with self.subTest(report=report):
                self.assertFalse(self.gate.validate(report))

    def test_rejects_failed_unattempted_mock_or_missing_model(self):
        for override in ({"success": False}, {"attempted": False},
                         {"provider": "mock"}, {"model": ""}, {"model": "  "}):
            with self.subTest(override=override):
                self.assertFalse(self.gate.validate(self.report(**override)))

    def test_rejects_truthy_non_boolean_status(self):
        for override in ({"success": "true"}, {"success": 1}, {"attempted": 1}):
            self.assertFalse(self.gate.validate(self.report(**override)))

    def test_rejects_partial_failure(self):
        report = self.report()
        report["results"].append(self.report(provider="gemini", success=False)["results"][0])
        self.assertFalse(self.gate.validate(report))

    def test_rejects_malformed_payloads_without_raising(self):
        for report in (None, [], 1, "completed", {"liveSmoke": "completed", "results": [None]},
                       self.report(provider=[]), self.report(model=1)):
            self.assertFalse(self.gate.validate(report))

    def test_cli_rejects_bad_json_without_echoing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            path.write_text('private-content-invalid-json', encoding="utf-8")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                result = self.gate.main([str(path)])
            self.assertNotEqual(result, 0)
            self.assertNotIn("private-content", output.getvalue())

    def test_cli_exit_status_tracks_report(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            for report, expected in ((self.report(), 0), ({"liveSmoke": "skipped"}, 1)):
                path.write_text(json.dumps(report), encoding="utf-8")
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(self.gate.main([str(path)]), expected)


if __name__ == "__main__":
    unittest.main()
