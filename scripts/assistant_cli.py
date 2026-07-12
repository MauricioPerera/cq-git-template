#!/usr/bin/env python3
"""CLI for one versioned assistant — same scoping rules as assistant_mcp_server.py.

For a human at a terminal or a script/CI step that wants an assistant's
profile or permitted knowledge without speaking MCP. Only dependency:
`pyyaml` (unlike assistant_mcp_server.py, this does not need the `mcp`
package).

Usage:
  python scripts/assistant_cli.py <repo-root> <slug> profile
  python scripts/assistant_cli.py <repo-root> <slug> list
  python scripts/assistant_cli.py <repo-root> <slug> search <query...>
  python scripts/assistant_cli.py <repo-root> <slug> get <ku_id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import assistant_summary as asum
import validate


def _load_assistant(root: Path, slug: str) -> dict:
    assistant_dir = root / "assistants" / slug
    if not (assistant_dir / "assistant.md").is_file():
        print(f"error: no assistant at {assistant_dir} (expected assistant.md)", file=sys.stderr)
        sys.exit(2)
    frontmatter, body = asum.parse_document(assistant_dir / "assistant.md")
    knowledge_text = (assistant_dir / "knowledge.md").read_text(encoding="utf-8")
    permitted = asum.knowledge_references(knowledge_text)
    units = asum.collect_units(root)
    confirms, _ = asum.event_counts(root, "confirmations", set(units))
    flags, _ = asum.event_counts(root, "flags", set(units))
    constants = json.loads((root / ".cq" / "scoring.values.json").read_text(encoding="utf-8"))[
        "confidence_constants"
    ]
    return {
        "frontmatter": frontmatter,
        "instructions": asum.section(body, "Instructions"),
        "permitted": permitted,
        "units": units,
        "confirms": confirms,
        "flags": flags,
        "constants": constants,
    }


def _confidence(state: dict, ku_id: str) -> float:
    c, f, k = state["confirms"].get(ku_id, 0), state["flags"].get(ku_id, 0), state["constants"]
    return max(k["floor"], min(k["ceiling"], k["initial"] + k["confirmation_boost"] * c - k["flag_penalty"] * f))


def cmd_profile(state: dict, slug: str) -> str:
    fm = state["frontmatter"]
    return "\n".join(
        [
            f"# {fm.get('id', slug)}",
            "",
            fm.get("description", ""),
            "",
            f"- Language: `{fm.get('language', '')}`",
            f"- Knowledge policy: `{fm.get('knowledge_policy', '')}`",
            f"- Flag policy: `{fm.get('flag_policy', '')}`",
            f"- Knowledge units in scope: {len(state['permitted'])}",
            "",
            "## Instructions",
            "",
            state["instructions"],
        ]
    )


def cmd_list(state: dict) -> str:
    lines = ["| id | confidence | description |", "|---|---|---|"]
    for ku_id in state["permitted"]:
        if ku_id not in state["units"]:
            lines.append(f"| `{ku_id}` | missing | _knowledge unit not found in units/_ |")
            continue
        fm, _body = state["units"][ku_id]
        lines.append(f"| `{ku_id}` | {_confidence(state, ku_id):.2f} | {fm.get('description', '')} |")
    return "\n".join(lines)


def cmd_search(state: dict, query: str) -> str:
    terms = [t for t in query.lower().split() if t]
    scored = []
    for ku_id in state["permitted"]:
        if ku_id not in state["units"]:
            continue
        fm, body = state["units"][ku_id]
        haystack = " ".join(
            [fm.get("description", ""), asum.section(body, "Insight"), asum.section(body, "Action")]
        ).lower()
        score = sum(1 for t in terms if t in haystack)
        if score:
            scored.append((score, ku_id, fm))
    if not scored:
        return f"No matches for '{query}' in this assistant's permitted knowledge."
    scored.sort(key=lambda row: row[0], reverse=True)
    lines = [f"# Matches for '{query}'", ""]
    for score, ku_id, fm in scored:
        lines.append(f"## `{ku_id}` (score {score})")
        lines.append(f"\n{fm.get('description', '')}")
        lines.append(f"\nConfidence: {_confidence(state, ku_id):.2f}\n")
    return "\n".join(lines)


def cmd_get(state: dict, ku_id: str) -> str:
    if ku_id not in state["permitted"]:
        return f"Error: `{ku_id}` is not in this assistant's knowledge.md — out of scope."
    if ku_id not in state["units"]:
        return f"Error: `{ku_id}` is listed in knowledge.md but does not exist in units/."
    fm, body = state["units"][ku_id]
    citations = asum.section(body, "Citations")
    if state["frontmatter"].get("knowledge_policy") == "cited_only" and not validate.has_usable_citation(body):
        return f"Error: `{ku_id}` has no usable citation, required by this assistant's cited_only policy."
    return "\n".join(
        [
            f"# `{ku_id}`",
            "",
            fm.get("description", ""),
            "",
            f"Confidence: {_confidence(state, ku_id):.2f}",
            "",
            "## Insight",
            "",
            asum.section(body, "Insight"),
            "",
            "## Action",
            "",
            asum.section(body, "Action"),
            "",
            "## Citations",
            "",
            citations or "_No citations._",
        ]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", help="repo root")
    parser.add_argument("slug", help="assistant directory name under assistants/")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("profile", help="identity + instructions")
    sub.add_parser("list", help="permitted knowledge units with confidence")
    search_p = sub.add_parser("search", help="search permitted knowledge")
    search_p.add_argument("query", nargs="+", help="search terms")
    get_p = sub.add_parser("get", help="fetch one permitted knowledge unit in full")
    get_p.add_argument("ku_id", help="exact knowledge unit id")

    args = parser.parse_args()
    root = Path(args.root).resolve()
    state = _load_assistant(root, args.slug)

    if args.command == "profile":
        print(cmd_profile(state, args.slug))
    elif args.command == "list":
        print(cmd_list(state))
    elif args.command == "search":
        print(cmd_search(state, " ".join(args.query)))
    elif args.command == "get":
        print(cmd_get(state, args.ku_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
