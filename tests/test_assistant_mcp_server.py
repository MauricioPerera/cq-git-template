"""Regression tests for scripts/assistant_mcp_server.py.

The module validates CQ_ASSISTANT_ROOT/CQ_ASSISTANT_SLUG at import time, so
each test loads a fresh module instance (importlib doesn't touch
sys.modules here) with the env vars set for that specific case.
"""

from __future__ import annotations

import asyncio
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fixtures import build_repo, CITED_KU_ID, KU_ID, SLUG  # noqa: E402

OUT_OF_SCOPE_KU_ID = "ku_ffffffffffffffffffffffffffffffff"


def load_server(root: Path, slug: str | None):
    env = {"CQ_ASSISTANT_ROOT": str(root)}
    if slug is not None:
        env["CQ_ASSISTANT_SLUG"] = slug
    with mock.patch.dict("os.environ", env, clear=False):
        spec = importlib.util.spec_from_file_location(
            "assistant_mcp_server", ROOT / "scripts" / "assistant_mcp_server.py"
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module


class AssistantMcpServerTests(unittest.TestCase):
    def setUp(self):
        self._temp = tempfile.TemporaryDirectory()
        self.root = Path(self._temp.name)
        build_repo(self.root)
        self.server = load_server(self.root, SLUG)

    def tearDown(self):
        self._temp.cleanup()

    def test_exits_when_slug_env_var_is_missing(self):
        with self.assertRaises(SystemExit):
            load_server(self.root, None)

    def test_exits_when_assistant_directory_does_not_exist(self):
        with self.assertRaises(SystemExit):
            load_server(self.root, "missing-slug")

    def test_get_profile_includes_instructions_and_scope_count(self):
        output = asyncio.run(self.server.cq_assistant_get_profile())
        self.assertIn("Be concise.", output)
        self.assertIn("Knowledge units in scope: 2", output)

    def test_list_knowledge_reports_every_permitted_ku(self):
        output = asyncio.run(self.server.cq_assistant_list_knowledge())
        self.assertIn(KU_ID, output)
        self.assertIn(CITED_KU_ID, output)

    def test_search_knowledge_only_matches_permitted_kus(self):
        params = self.server.SearchKnowledgeInput(query="idempotent")
        output = asyncio.run(self.server.cq_assistant_search_knowledge(params))
        self.assertIn(CITED_KU_ID, output)
        self.assertNotIn(KU_ID, output)

    def test_get_knowledge_returns_full_content_for_a_cited_ku(self):
        params = self.server.GetKnowledgeInput(ku_id=CITED_KU_ID)
        output = asyncio.run(self.server.cq_assistant_get_knowledge(params))
        self.assertIn("Webhook retry idempotency.", output)
        self.assertIn("[Stripe docs](https://stripe.com/docs)", output)

    def test_get_knowledge_rejects_uncited_ku_under_cited_only_policy(self):
        params = self.server.GetKnowledgeInput(ku_id=KU_ID)
        output = asyncio.run(self.server.cq_assistant_get_knowledge(params))
        self.assertTrue(output.startswith("Error:"))
        self.assertIn("cited_only", output)

    def test_get_knowledge_rejects_ku_outside_knowledge_md(self):
        params = self.server.GetKnowledgeInput(ku_id=OUT_OF_SCOPE_KU_ID)
        output = asyncio.run(self.server.cq_assistant_get_knowledge(params))
        self.assertTrue(output.startswith("Error:"))
        self.assertIn("out of scope", output)


if __name__ == "__main__":
    unittest.main()
