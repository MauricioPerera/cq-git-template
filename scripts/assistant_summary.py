#!/usr/bin/env python3
"""Render a read-only Markdown summary of one versioned assistant."""

from __future__ import annotations

import json
import datetime
import re
import sys
from pathlib import Path

import yaml

KU_ID_RE = re.compile(r"ku_[0-9a-f]{32}")
RESERVED = {"index.md", "log.md"}
LIST_KU_RE = re.compile(r"^\s{0,3}(?:[-+*]|\d+[.)])\s+`?(ku_[0-9a-f]{32})`?\s*$")
FLAG_REASONS = {"stale", "incorrect", "duplicate"}


def parse_document(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not match:
        raise ValueError(f"{path}: missing or invalid frontmatter")
    frontmatter = yaml.safe_load(match.group(1))
    if not isinstance(frontmatter, dict):
        raise ValueError(f"{path}: frontmatter must be a mapping")
    return frontmatter, match.group(2)


def section(body: str, heading: str) -> str:
    match = re.search(
        rf"^# {re.escape(heading)}\s*$\n(.*?)(?=^# |\Z)", body, re.MULTILINE | re.DOTALL
    )
    return match.group(1).strip() if match else ""


def knowledge_references(text: str) -> list[str]:
    """Return exact KU ids from list items in the top-level Knowledge section."""
    knowledge = section(text, "Knowledge")
    references: list[str] = []
    for line in knowledge.splitlines():
        match = LIST_KU_RE.fullmatch(line)
        if match:
            references.append(match.group(1))
    return references


def is_iso8601(value: object) -> bool:
    if isinstance(value, (datetime.datetime, datetime.date)):
        return True
    if not isinstance(value, str):
        return False
    try:
        datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return True


def event_counts(
    root: Path, kind: str, known_ids: set[str] | None = None
) -> tuple[dict[str, int], list[str]]:
    counts: dict[str, int] = {}
    warnings: list[str] = []
    base = root / "events" / kind
    if not base.is_dir():
        return counts, warnings
    if known_ids is None:
        known_ids = set(collect_units(root))
    expected_type = {"confirmations": "Confirmation", "flags": "Flag"}.get(kind)
    if expected_type is None:
        return counts, [f"unknown event kind {kind!r}"]
    for path in base.rglob("*.md"):
        if path.name in RESERVED:
            continue
        try:
            fm, _ = parse_document(path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            warnings.append(f"skipping invalid event {path}: {exc}")
            continue
        unit, problems = fm.get("unit"), []
        if fm.get("type") != expected_type:
            problems.append(f"type must be {expected_type}")
        if not isinstance(unit, str) or not KU_ID_RE.fullmatch(unit):
            problems.append("unit must be a valid KU id")
        elif unit not in known_ids:
            problems.append(f"unit {unit} does not exist")
        elif path.parent.name != unit:
            problems.append("parent directory must equal unit")
        if not is_iso8601(fm.get("timestamp")):
            problems.append("timestamp must be ISO 8601")
        if expected_type == "Flag":
            reason, duplicate_of = fm.get("reason"), fm.get("duplicate_of")
            if reason not in FLAG_REASONS:
                problems.append("invalid flag reason")
            if reason == "duplicate":
                if not isinstance(duplicate_of, str) or not KU_ID_RE.fullmatch(duplicate_of):
                    problems.append("duplicate_of must be a valid KU id for duplicate flags")
                elif duplicate_of not in known_ids:
                    problems.append(f"duplicate_of {duplicate_of} does not exist")
            elif duplicate_of is not None:
                problems.append("duplicate_of is only allowed for duplicate flags")
        if problems:
            warnings.append(f"skipping invalid event {path}: {'; '.join(problems)}")
            continue
        counts[unit] = counts.get(unit, 0) + 1
    return counts, warnings


def collect_units(root: Path) -> dict[str, tuple[dict, str]]:
    units: dict[str, tuple[dict, str]] = {}
    for path in (root / "units").rglob("*.md"):
        try:
            fm, body = parse_document(path)
        except (OSError, ValueError, yaml.YAMLError):
            continue
        ku_id = fm.get("id")
        if fm.get("type") == "KnowledgeUnit" and isinstance(ku_id, str) and KU_ID_RE.fullmatch(ku_id):
            units[ku_id] = (fm, body)
    return units


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: python scripts/assistant_summary.py <repo-root> <assistant-slug>", file=sys.stderr)
        return 2

    root = Path(sys.argv[1]).resolve()
    slug = sys.argv[2]
    assistant_dir = root / "assistants" / slug
    try:
        assistant, assistant_body = parse_document(assistant_dir / "assistant.md")
        references = knowledge_references((assistant_dir / "knowledge.md").read_text(encoding="utf-8"))
        constants = json.loads((root / ".cq" / "scoring.values.json").read_text(encoding="utf-8"))[
            "confidence_constants"
        ]
    except (OSError, ValueError, yaml.YAMLError, json.JSONDecodeError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    units = collect_units(root)

    confirms, confirm_warnings = event_counts(root, "confirmations", set(units))
    flags, flag_warnings = event_counts(root, "flags", set(units))
    for warning in confirm_warnings + flag_warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"# {assistant.get('id', slug)}")
    print(f"\n{assistant.get('description', '')}")
    print("\n## Identity")
    print(f"\n- Language: `{assistant.get('language', '')}`")
    print(f"- Knowledge policy: `{assistant.get('knowledge_policy', '')}`")
    print(f"- Flag policy: `{assistant.get('flag_policy', '')}`")
    print("\n## Instructions")
    print(f"\n{section(assistant_body, 'Instructions')}")
    print("\n## Knowledge units")
    for ku_id in references:
        if ku_id not in units:
            print(f"\n### `{ku_id}`\n\nMissing knowledge unit.")
            continue
        fm, body = units[ku_id]
        confirm_count, flag_count = confirms.get(ku_id, 0), flags.get(ku_id, 0)
        confidence = max(
            constants["floor"],
            min(
                constants["ceiling"],
                constants["initial"]
                + constants["confirmation_boost"] * confirm_count
                - constants["flag_penalty"] * flag_count,
            ),
        )
        print(f"\n### `{ku_id}`")
        print(f"\n**Description:** {fm.get('description', '')}")
        print(f"\n**Confidence:** {confidence:.2f} ({confirm_count} confirmations, {flag_count} flags)")
        citations = section(body, "Citations")
        print(f"\n**Citations:**\n\n{citations or '_No citations._'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
