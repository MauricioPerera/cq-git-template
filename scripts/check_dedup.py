#!/usr/bin/env python3
"""Near-duplicate detection for knowledge units.

Compares KUs pairwise on domain Jaccard similarity and description token
overlap. Meant as a *warning* signal in PRs: if a new KU closely matches an
existing one, the right move is usually a confirmation (same insight) or a
duplicate flag (contradicts it), not a new unit.

Usage:
  check_dedup.py --all                 # compare every KU against every other
  check_dedup.py units/a.md units/b.md # compare only these files vs the rest

Exit code is always 0 (warn-only) unless --strict is passed, in which case any
finding above the threshold exits 1.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

STOPWORDS = {
    "a", "an", "the", "is", "are", "for", "with", "of", "in", "on", "to",
    "and", "or", "when", "instead", "returns", "return",
}
THRESHOLD = 0.6  # combined score above which a pair is reported


def load_kus(root: Path) -> list[dict]:
    kus = []
    for path in sorted((root / "units").rglob("*.md")):
        m = re.match(r"^---\s*\n(.*?)\n---", path.read_text(encoding="utf-8"), re.DOTALL)
        fm = yaml.safe_load(m.group(1)) if m else None
        if isinstance(fm, dict) and fm.get("type") == "KnowledgeUnit":
            kus.append(
                {
                    "path": path,
                    "id": fm.get("id", "?"),
                    "domains": {str(d).lower() for d in fm.get("domains") or []},
                    "tokens": {
                        t
                        for t in re.findall(r"[a-z0-9]+", str(fm.get("description", "")).lower())
                        if t not in STOPWORDS
                    },
                }
            )
    return kus


def jaccard(a: set, b: set) -> float:
    return len(a & b) / len(a | b) if a | b else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", help="changed KU files to check (paths)")
    ap.add_argument("--all", action="store_true", help="check every pair")
    ap.add_argument("--strict", action="store_true", help="exit 1 on findings")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = ap.parse_args()

    root = Path(args.root)
    kus = load_kus(root)
    changed = {Path(f).resolve() for f in args.files}
    findings = []

    for i, a in enumerate(kus):
        for b in kus[i + 1 :]:
            if not args.all and changed and not (
                a["path"].resolve() in changed or b["path"].resolve() in changed
            ):
                continue
            score = 0.6 * jaccard(a["domains"], b["domains"]) + 0.4 * jaccard(
                a["tokens"], b["tokens"]
            )
            if score >= THRESHOLD:
                findings.append((score, a, b))

    if findings:
        print(f"Possible near-duplicates (score >= {THRESHOLD}):")
        for score, a, b in sorted(findings, reverse=True, key=lambda x: x[0]):
            print(f"  {score:.2f}  {a['path'].as_posix()}  <->  {b['path'].as_posix()}")
        print("Consider a confirmation or a duplicate flag instead of a new unit.")
        return 1 if args.strict else 0
    print("No near-duplicates found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
