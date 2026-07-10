#!/usr/bin/env python3
"""Validate a cq-git knowledge repo.

Checks (all errors, exit 1 if any):
  OKF conformance
    - every non-reserved .md under units/ and events/ has parseable YAML
      frontmatter with a non-empty `type`
  Knowledge units (type: KnowledgeUnit)
    - id matches ^ku_[0-9a-f]{32}$ and is unique across the repo
    - description is a non-empty string
    - domains is a non-empty list of strings
    - superseded_by, when set, matches the ku_ pattern
    - body contains `# Insight` and `# Action` headings
  Events
    - confirmations have type Confirmation; flags have type Flag
    - unit matches the ku_ pattern and exists in this repo
    - parent directory name equals the unit field
    - timestamp present and ISO 8601-parseable
    - flags: reason in {stale, incorrect, duplicate};
      duplicate_of required iff reason == duplicate, and must match the pattern
  Config
    - .cq/scoring.values.json parses and has the required keys

Only dependency: pyyaml.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

import yaml

KU_ID_RE = re.compile(r"^ku_[0-9a-f]{32}$")
RESERVED = {"index.md", "log.md"}
FLAG_REASONS = {"stale", "incorrect", "duplicate"}
REQUIRED_SCORING_KEYS = {
    "relevance_weights": {"domain", "language", "framework", "pattern"},
    "confidence_constants": {
        "initial",
        "confirmation_boost",
        "flag_penalty",
        "ceiling",
        "floor",
    },
}

errors: list[str] = []


def err(path: Path, msg: str) -> None:
    errors.append(f"{path.as_posix()}: {msg}")


def parse_frontmatter(path: Path) -> tuple[dict | None, str]:
    """Return (frontmatter dict, body). None frontmatter means a parse error."""
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        err(path, "missing YAML frontmatter block")
        return None, text
    parts = text.split("\n---", 2)
    # parts[0] is "---" plus the first line of yaml when the file starts with "---\n"
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.DOTALL)
    if not m:
        err(path, "unterminated frontmatter block")
        return None, text
    try:
        fm = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        err(path, f"frontmatter is not valid YAML: {e}")
        return None, m.group(2)
    if not isinstance(fm, dict):
        err(path, "frontmatter must be a YAML mapping")
        return None, m.group(2)
    return fm, m.group(2)


def check_timestamp(path: Path, value: object, field: str = "timestamp") -> None:
    if value is None:
        err(path, f"missing `{field}`")
        return
    if isinstance(value, (datetime.datetime, datetime.date)):
        return  # yaml already parsed it as a datetime
    if isinstance(value, str):
        try:
            datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
            return
        except ValueError:
            pass
    err(path, f"`{field}` is not ISO 8601: {value!r}")


def collect_units(root: Path) -> dict[str, Path]:
    """Validate unit docs; return {ku_id: path}."""
    ids: dict[str, Path] = {}
    units_dir = root / "units"
    if not units_dir.is_dir():
        return ids
    for path in sorted(units_dir.rglob("*.md")):
        if path.name in RESERVED:
            continue
        fm, body = parse_frontmatter(path)
        if fm is None:
            continue
        ctype = fm.get("type")
        if not isinstance(ctype, str) or not ctype.strip():
            err(path, "missing or empty `type` (OKF requires it)")
            continue
        if ctype != "KnowledgeUnit":
            continue  # other OKF concepts are allowed under units/

        ku_id = fm.get("id")
        if not isinstance(ku_id, str) or not KU_ID_RE.match(ku_id):
            err(path, f"`id` must match ^ku_[0-9a-f]{{32}}$ (got {ku_id!r})")
        elif ku_id in ids:
            err(path, f"duplicate id {ku_id} (also in {ids[ku_id].as_posix()})")
        else:
            ids[ku_id] = path

        desc = fm.get("description")
        if not isinstance(desc, str) or not desc.strip():
            err(path, "missing or empty `description`")

        domains = fm.get("domains")
        if (
            not isinstance(domains, list)
            or not domains
            or not all(isinstance(d, str) and d.strip() for d in domains)
        ):
            err(path, "`domains` must be a non-empty list of strings")

        sup = fm.get("superseded_by")
        if sup is not None and (not isinstance(sup, str) or not KU_ID_RE.match(sup)):
            err(path, f"`superseded_by` must be null or a ku_ id (got {sup!r})")

        check_timestamp(path, fm.get("timestamp"))

        for heading in ("# Insight", "# Action"):
            if not re.search(rf"^{re.escape(heading)}\s*$", body, re.MULTILINE):
                err(path, f"body is missing required `{heading}` heading")
    return ids


def check_events(root: Path, known_ids: dict[str, Path]) -> None:
    for kind, expected_type in (("confirmations", "Confirmation"), ("flags", "Flag")):
        base = root / "events" / kind
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.md")):
            fm, _body = parse_frontmatter(path)
            if fm is None:
                continue
            if fm.get("type") != expected_type:
                err(path, f"`type` must be {expected_type} (got {fm.get('type')!r})")

            unit = fm.get("unit")
            if not isinstance(unit, str) or not KU_ID_RE.match(unit):
                err(path, f"`unit` must be a ku_ id (got {unit!r})")
            else:
                if unit not in known_ids:
                    err(path, f"`unit` {unit} does not exist in this repo")
                if path.parent.name != unit:
                    err(
                        path,
                        f"parent directory {path.parent.name!r} must equal `unit` {unit}",
                    )

            check_timestamp(path, fm.get("timestamp"))

            if expected_type == "Flag":
                reason = fm.get("reason")
                if reason not in FLAG_REASONS:
                    err(path, f"`reason` must be one of {sorted(FLAG_REASONS)} (got {reason!r})")
                dup = fm.get("duplicate_of")
                if reason == "duplicate":
                    if not isinstance(dup, str) or not KU_ID_RE.match(dup):
                        err(path, "`duplicate_of` (ku_ id) is required when reason == duplicate")
                elif dup is not None:
                    err(path, "`duplicate_of` is only allowed when reason == duplicate")


def check_scoring(root: Path) -> None:
    path = root / ".cq" / "scoring.values.json"
    if not path.is_file():
        err(path, "missing scoring values file")
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        err(path, f"invalid JSON: {e}")
        return
    for section, keys in REQUIRED_SCORING_KEYS.items():
        got = data.get(section)
        if not isinstance(got, dict):
            err(path, f"missing section `{section}`")
            continue
        missing = keys - got.keys()
        if missing:
            err(path, f"section `{section}` missing keys: {sorted(missing)}")


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    known_ids = collect_units(root)
    check_events(root, known_ids)
    check_scoring(root)

    if errors:
        print(f"FAIL — {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(f"OK — {len(known_ids)} knowledge unit(s) validated, events and config consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
