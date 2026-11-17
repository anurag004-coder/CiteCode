"""Regression coverage for Python and JavaScript potential-impact call sites."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.impact import analyze_repository


class ImpactAnalysisTests(unittest.TestCase):
    def test_python_direct_callers_and_test_sites_link_to_indexed_lines(self):
        repository = {"full_name": "acme/sample", "commit_sha": "pinned-sha"}
        files = {
            "src/parser.py": {"content": "def parse_token(value):\n    return value.strip()\n"},
            "src/handler.py": {"content": "from src.parser import parse_token\n\ndef handle(value):\n    return parse_token(value)\n"},
            "tests/test_parser.py": {"content": "def test_parse_token():\n    assert parse_token(' x ') == 'x'\n"},
        }

        targets = analyze_repository(repository, files)["targets"]
        target = next(item for item in targets if item["path"] == "src/parser.py" and item["name"] == "parse_token")
        result = analyze_repository(repository, files, target["path"], target["name"], target["start_line"])
        impact = result["potential_impact"]

        self.assertEqual([(item["path"], item["line"]) for item in impact["direct_callers"]], [
            ("src/handler.py", 4),
        ])
        self.assertEqual([(item["path"], item["line"]) for item in impact["likely_tests"]], [
            ("tests/test_parser.py", 2),
        ])
        self.assertTrue(all("pinned-sha" in item["url"] and "#L" in item["url"]
                            for item in impact["direct_callers"] + impact["likely_tests"]))

    def test_javascript_calls_from_spec_files_are_likely_tests(self):
        repository = {"full_name": "acme/sample", "commit_sha": "pinned-sha"}
        files = {
            "src/normalize.js": {"content": "export function normalize(value) { return value.trim(); }\n"},
            "src/consumer.js": {"content": "export function prepare(value) { return normalize(value); }\n"},
            "src/normalize.spec.js": {"content": "test('normalizes', () => normalize(' x '));\n"},
        }

        targets = analyze_repository(repository, files)["targets"]
        target = next(item for item in targets if item["path"] == "src/normalize.js" and item["name"] == "normalize")
        impact = analyze_repository(repository, files, target["path"], target["name"], target["start_line"])["potential_impact"]

        self.assertTrue(any(item["path"] == "src/consumer.js" for item in impact["direct_callers"]))
        self.assertTrue(any(item["path"] == "src/normalize.spec.js" for item in impact["likely_tests"]))
        self.assertIn("Dynamic calls may be missed", impact["limitations"])
        self.assertIn("resolve ambiguously", impact["limitations"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
