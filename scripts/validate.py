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
  Assistants
    - every assistants/<slug>/assistant.md has valid Assistant frontmatter
    - assistant ids are valid and unique; language and policies are supported
    - knowledge.md contains only unique references to KUs that exist
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
ASSISTANT_ID_RE = re.compile(r"^assistant_[a-z0-9][a-z0-9_-]*$")
LANGUAGE_RE = re.compile(r"^[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*$")
LIST_KU_RE = re.compile(
    r"^\s{0,3}(?:[-+*]|\d+[.)])\s+`?(ku_[0-9a-f]{32})`?\s*$"
)
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]\n]+\]\(\s*[^)\s][^)]*\)")
RESERVED = {"index.md", "log.md"}
FLAG_REASONS = {"stale", "incorrect", "duplicate"}
KNOWLEDGE_POLICIES = {"cited_only"}
FLAG_POLICIES = {"warn"}
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


def knowledge_references(text: str) -> list[str]:
    """Return exact KU ids from list items in the top-level Knowledge section."""
    match = re.search(r"^# Knowledge\s*$\n(.*?)(?=^# |\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        return []
    references: list[str] = []
    for line in match.group(1).splitlines():
        list_match = LIST_KU_RE.fullmatch(line)
        if list_match:
            references.append(list_match.group(1))
    return references


def has_usable_citation(body: str) -> bool:
    match = re.search(
        r"^# Citations\s*$\n(.*?)(?=^# |\Z)", body, re.MULTILINE | re.DOTALL
    )
    return bool(match and MARKDOWN_LINK_RE.search(match.group(1)))


def check_assistants_index(base: Path, directories: list[Path]) -> None:
    index_path = base / "index.md"
    if not index_path.is_file():
        err(index_path, "missing assistants index")
        return
    text = index_path.read_text(encoding="utf-8")
    if not re.search(r"^# Assistants\s*$", text, re.MULTILINE):
        err(index_path, "missing required `# Assistants` heading")
    links = [target for _label, target in re.findall(r"\[([^]\n]+)\]\(([^)\n]+)\)", text)]
    expected = {f"{directory.name}/assistant.md" for directory in directories}
    for target in sorted(expected):
        count = links.count(target)
        if count == 0:
            err(index_path, f"missing Markdown link to `{target}`")
        elif count > 1:
            err(index_path, f"duplicate Markdown link to `{target}`")
    for target in sorted(set(links) - expected):
        err(index_path, f"unexpected assistant link `{target}`; targets must be exactly `<slug>/assistant.md`")


def check_assistants(root: Path, known_ids: dict[str, Path]) -> int:
    """Validate assistant definitions and KU links; return assistant count."""
    base = root / "assistants"
    if not base.exists():
        return 0
    if not base.is_dir():
        err(base, "must be a directory")
        return 0

    directories = sorted(path for path in base.iterdir() if path.is_dir())
    check_assistants_index(base, directories)
    assistant_ids: dict[str, Path] = {}
    count = 0
    for directory in directories:
        assistant_path = directory / "assistant.md"
        knowledge_path = directory / "knowledge.md"
        if not assistant_path.is_file():
            err(assistant_path, "missing assistant definition")
            continue

        count += 1
        fm, body = parse_frontmatter(assistant_path)
        if fm is not None:
            if fm.get("type") != "Assistant":
                err(assistant_path, f"`type` must be Assistant (got {fm.get('type')!r})")

            assistant_id = fm.get("id")
            if not isinstance(assistant_id, str) or not ASSISTANT_ID_RE.match(assistant_id):
                err(assistant_path, "`id` must match ^assistant_[a-z0-9][a-z0-9_-]*$")
            elif assistant_id in assistant_ids:
                err(
                    assistant_path,
                    f"duplicate id {assistant_id} (also in {assistant_ids[assistant_id].as_posix()})",
                )
            else:
                assistant_ids[assistant_id] = assistant_path

            description = fm.get("description")
            if not isinstance(description, str) or not description.strip():
                err(assistant_path, "missing or empty `description`")
            language = fm.get("language")
            if not isinstance(language, str) or not LANGUAGE_RE.fullmatch(language):
                err(assistant_path, "`language` must be a non-empty simple BCP-47 code (for example `es` or `en-US`)")
            if fm.get("knowledge_policy") not in KNOWLEDGE_POLICIES:
                err(assistant_path, "`knowledge_policy` must be cited_only")
            if fm.get("flag_policy") not in FLAG_POLICIES:
                err(assistant_path, "`flag_policy` must be warn")
            if not re.search(r"^# Instructions\s*$", body, re.MULTILINE):
                err(assistant_path, "body is missing required `# Instructions` heading")

        if not knowledge_path.is_file():
            err(knowledge_path, "missing knowledge list")
            continue
        knowledge_text = knowledge_path.read_text(encoding="utf-8")
        if not re.search(r"^# Knowledge\s*$", knowledge_text, re.MULTILINE):
            err(knowledge_path, "missing required `# Knowledge` heading")
        references = knowledge_references(knowledge_text)
        if not references:
            err(knowledge_path, "must reference at least one exact KU id as an explicit Markdown list item under `# Knowledge`")
        seen: set[str] = set()
        for ku_id in references:
            if ku_id in seen:
                err(knowledge_path, f"duplicate KU reference {ku_id}")
            seen.add(ku_id)
            if ku_id not in known_ids:
                err(knowledge_path, f"referenced KU {ku_id} does not exist in this repo")
            elif fm is not None and fm.get("knowledge_policy") == "cited_only":
                _unit_fm, unit_body = parse_frontmatter(known_ids[ku_id])
                if not has_usable_citation(unit_body):
                    err(
                        knowledge_path,
                        f"referenced KU {ku_id} must have `# Citations` with at least one usable Markdown link for `cited_only`",
                    )
    return count


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
    errors.clear()
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    known_ids = collect_units(root)
    check_events(root, known_ids)
    assistant_count = check_assistants(root, known_ids)
    check_scoring(root)

    if errors:
        print(f"FAIL — {len(errors)} error(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    print(
        f"OK — {len(known_ids)} knowledge unit(s) and {assistant_count} assistant(s) "
        "validated; events and config consistent."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
