"""Regression tests for assistant validation and summaries."""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


validate = load_script("validate")
summary = load_script("assistant_summary")
KU_ID = "ku_0123456789abcdef0123456789abcdef"


class KnowledgeReferenceTests(unittest.TestCase):
    def test_accepts_only_exact_markdown_list_references_under_knowledge(self):
        text = (
            f"- {KU_ID}\n\n# Knowledge\n\n"
            f"Text mentioning `{KU_ID}` is not a reference.\n\n- `{KU_ID}`\n"
            f"\n# Notes\n\n- {KU_ID}\n"
        )
        self.assertEqual(validate.knowledge_references(text), [KU_ID])
        self.assertEqual(summary.knowledge_references(text), [KU_ID])

    def test_rejects_substrings_and_incidental_text(self):
        text = f"prefix{KU_ID}suffix\n`{KU_ID}extra`\nplain {KU_ID}\n"
        self.assertEqual(validate.knowledge_references(text), [])

    def test_requires_a_link_inside_citations_section(self):
        self.assertFalse(validate.has_usable_citation("# Citations\n\nNo link here."))
        self.assertFalse(validate.has_usable_citation("# Notes\n\n[Source](https://example.test)"))
        self.assertTrue(validate.has_usable_citation("# Citations\n\n[Source](https://example.test)"))

    def test_accepts_simple_bcp47_codes(self):
        for language in ("es", "en-US", "zh-Hant-TW"):
            self.assertIsNotNone(validate.LANGUAGE_RE.fullmatch(language))
        for language in ("", "e", "es_MX", "-es"):
            self.assertIsNone(validate.LANGUAGE_RE.fullmatch(language))


class EventSummaryTests(unittest.TestCase):
    def test_invalid_events_are_reported_and_reserved_files_are_ignored(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "events" / "confirmations"
            base.mkdir(parents=True)
            (base / "index.md").write_text("not frontmatter", encoding="utf-8")
            (base / "broken.md").write_text("---\n: invalid: yaml\n---\n", encoding="utf-8")
            counts, warnings = summary.event_counts(Path(temp), "confirmations")
        self.assertEqual(counts, {})
        self.assertEqual(len(warnings), 1)
        self.assertIn("broken.md", warnings[0])

    def test_counts_only_semantically_valid_events(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unit_dir = root / "units"
            unit_dir.mkdir()
            (unit_dir / "unit.md").write_text(
                f"---\ntype: KnowledgeUnit\nid: {KU_ID}\n---\n", encoding="utf-8"
            )
            base = root / "events" / "confirmations" / KU_ID
            base.mkdir(parents=True)
            valid = f"---\ntype: Confirmation\nunit: {KU_ID}\ntimestamp: 2026-07-10T14:30:05Z\n---\n"
            (base / "valid.md").write_text(valid, encoding="utf-8")
            (base / "wrong-type.md").write_text(valid.replace("Confirmation", "Flag"), encoding="utf-8")
            (base / "bad-time.md").write_text(valid.replace("2026-07-10T14:30:05Z", "yesterday"), encoding="utf-8")
            wrong_parent = root / "events" / "confirmations" / "elsewhere"
            wrong_parent.mkdir()
            (wrong_parent / "wrong-parent.md").write_text(valid, encoding="utf-8")

            counts, warnings = summary.event_counts(root, "confirmations")

        self.assertEqual(counts, {KU_ID: 1})
        self.assertEqual(len(warnings), 3)

    def test_rejects_incoherent_flags_without_raising(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            unit_dir = root / "units"
            unit_dir.mkdir()
            (unit_dir / "unit.md").write_text(
                f"---\ntype: KnowledgeUnit\nid: {KU_ID}\n---\n", encoding="utf-8"
            )
            base = root / "events" / "flags" / KU_ID
            base.mkdir(parents=True)
            event = f"---\ntype: Flag\nunit: {KU_ID}\ntimestamp: 2026-07-10T14:30:05Z\n"
            (base / "bad-reason.md").write_text(event + "reason: typo\n---\n", encoding="utf-8")
            (base / "bad-duplicate.md").write_text(event + "reason: duplicate\n---\n", encoding="utf-8")

            counts, warnings = summary.event_counts(root, "flags")

        self.assertEqual(counts, {})
        self.assertEqual(len(warnings), 2)


class AssistantIndexTests(unittest.TestCase):
    def test_index_requires_exact_bidirectional_links(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp) / "assistants"
            (base / "alpha").mkdir(parents=True)
            (base / "beta").mkdir()
            (base / "index.md").write_text(
                "# Assistants\n\n"
                "- [alpha](alpha/assistant.md)\n"
                "- [alpha again](alpha/assistant.md)\n"
                "- [broken](missing/assistant.md)\n"
                "- [outside](../README.md)\n",
                encoding="utf-8",
            )
            validate.errors.clear()
            validate.check_assistants_index(base, [base / "alpha", base / "beta"])
            output = "\n".join(validate.errors)

            base.joinpath("index.md").write_text(
                "# Assistants\n\n- [alpha]( alpha/assistant.md )\n", encoding="utf-8"
            )
            validate.errors.clear()
            validate.check_assistants_index(base, [base / "alpha"])
            spaced_output = "\n".join(validate.errors)

        self.assertIn("duplicate Markdown link to `alpha/assistant.md`", output)
        self.assertIn("missing Markdown link to `beta/assistant.md`", output)
        self.assertIn("unexpected assistant link `missing/assistant.md`", output)
        self.assertIn("unexpected assistant link `../README.md`", output)
        self.assertIn("missing Markdown link to `alpha/assistant.md`", spaced_output)


if __name__ == "__main__":
    unittest.main()
