#!/usr/bin/env python3
"""Print the derived confidence table for every knowledge unit.

Confidence is never stored in files. It is computed here from the append-only
event files, using the constants in .cq/scoring.values.json:

    confidence = clamp(initial + boost * confirmations - penalty * flags,
                       floor, ceiling)

Computing from counts (instead of replaying clamped increments) is
deterministic and order-independent.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml

KU_ID_RE = re.compile(r"^ku_[0-9a-f]{32}$")


def frontmatter(path: Path) -> dict:
    m = re.match(r"^---\s*\n(.*?)\n---", path.read_text(encoding="utf-8"), re.DOTALL)
    fm = yaml.safe_load(m.group(1)) if m else None
    return fm if isinstance(fm, dict) else {}


def count_events(base: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if base.is_dir():
        for path in base.rglob("*.md"):
            unit = frontmatter(path).get("unit")
            if isinstance(unit, str) and KU_ID_RE.match(unit):
                counts[unit] = counts.get(unit, 0) + 1
    return counts


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
    consts = json.loads((root / ".cq" / "scoring.values.json").read_text(encoding="utf-8"))[
        "confidence_constants"
    ]
    confirms = count_events(root / "events" / "confirmations")
    flags = count_events(root / "events" / "flags")

    rows = []
    for path in sorted((root / "units").rglob("*.md")):
        fm = frontmatter(path)
        if fm.get("type") != "KnowledgeUnit":
            continue
        ku_id = fm.get("id", "?")
        c, f = confirms.get(ku_id, 0), flags.get(ku_id, 0)
        confidence = max(
            consts["floor"],
            min(
                consts["ceiling"],
                consts["initial"] + consts["confirmation_boost"] * c - consts["flag_penalty"] * f,
            ),
        )
        rows.append((ku_id, c, f, confidence, fm.get("description", "")))

    print("| id | confirms | flags | confidence | description |")
    print("|---|---|---|---|---|")
    for ku_id, c, f, conf, desc in rows:
        print(f"| `{ku_id}` | {c} | {f} | {conf:.2f} | {desc} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
