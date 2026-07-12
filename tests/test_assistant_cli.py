"""Regression tests for scripts/assistant_cli.py."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import build_repo, CITED_KU_ID, KU_ID, SLUG  # noqa: E402


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


cli = load_script("assistant_cli")
OUT_OF_SCOPE_KU_ID = "ku_ffffffffffffffffffffffffffffffff"


class AssistantCliTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        build_repo(self.root)
        self.state = cli._load_assistant(self.root, SLUG)

    def tearDown(self):
        self._temp.cleanup()

    def test_load_assistant_exits_when_assistant_missing(self):
        with self.assertRaises(SystemExit):
            cli._load_assistant(self.root, "missing-slug")

    def test_profile_includes_instructions_and_scope_count(self):
        output = cli.cmd_profile(self.state, SLUG)
        self.assertIn("Be concise.", output)
        self.assertIn("Knowledge units in scope: 2", output)

    def test_list_reports_confidence_for_every_permitted_ku(self):
        output = cli.cmd_list(self.state)
        self.assertIn(f"`{KU_ID}`", output)
        self.assertIn(f"`{CITED_KU_ID}`", output)
        self.assertIn("0.50", output)  # initial confidence, no events yet

    def test_search_only_matches_permitted_kus_by_token(self):
        output = cli.cmd_search(self.state, "idempotent")
        self.assertIn(CITED_KU_ID, output)
        self.assertNotIn(KU_ID, output)

    def test_search_reports_no_matches_for_unrelated_query(self):
        output = cli.cmd_search(self.state, "unrelated nonsense query")
        self.assertTrue(output.startswith("No matches"))

    def test_get_returns_full_content_for_a_cited_ku(self):
        output = cli.cmd_get(self.state, CITED_KU_ID)
        self.assertIn("## Insight", output)
        self.assertIn("Webhook retry idempotency.", output)
        self.assertIn("[Stripe docs](https://stripe.com/docs)", output)

    def test_get_rejects_uncited_ku_under_cited_only_policy(self):
        output = cli.cmd_get(self.state, KU_ID)
        self.assertTrue(output.startswith("Error:"))
        self.assertIn("cited_only", output)

    def test_get_rejects_ku_outside_knowledge_md(self):
        output = cli.cmd_get(self.state, OUT_OF_SCOPE_KU_ID)
        self.assertTrue(output.startswith("Error:"))
        self.assertIn("out of scope", output)


if __name__ == "__main__":
    unittest.main()
