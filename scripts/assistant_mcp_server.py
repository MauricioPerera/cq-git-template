#!/usr/bin/env python3
"""MCP server that exposes one versioned assistant (assistants/<slug>/) as tools.

Unlike the generic BM25 MCP described in the README (which serves all of
units/ unscoped), this server enforces the assistant's own contract:
- only the KU ids listed in knowledge.md are ever returned;
- the assistant's `# Instructions` are exposed so a client can use them as
  its system prompt;
- `cited_only` is enforced at read time, not just by validate.py in CI.

Configuration (environment variables):
  CQ_ASSISTANT_ROOT  path to the repo root (default: parent of scripts/)
  CQ_ASSISTANT_SLUG  assistant directory name under assistants/ (required)

Run directly for stdio transport (the mode Claude Code expects):
  CQ_ASSISTANT_SLUG=soporte-stripe python scripts/assistant_mcp_server.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

import assistant_summary as asum
import validate

REPO_ROOT = Path(os.environ.get("CQ_ASSISTANT_ROOT", Path(__file__).resolve().parents[1]))
ASSISTANT_SLUG = os.environ.get("CQ_ASSISTANT_SLUG")

if not ASSISTANT_SLUG:
    print("error: CQ_ASSISTANT_SLUG env var is required (e.g. 'soporte-stripe')", file=sys.stderr)
    sys.exit(2)

ASSISTANT_DIR = REPO_ROOT / "assistants" / ASSISTANT_SLUG
if not (ASSISTANT_DIR / "assistant.md").is_file():
    print(f"error: no assistant at {ASSISTANT_DIR} (expected assistant.md)", file=sys.stderr)
    sys.exit(2)


def _load_assistant() -> dict:
    """Read the assistant definition and its permitted KU set from disk.

    Re-read on every call (not cached) so edits to assistant.md/knowledge.md
    take effect without restarting the server — these are the same files a
    reviewer edits via PR, and this server is meant to reflect them exactly.
    """
    frontmatter, body = asum.parse_document(ASSISTANT_DIR / "assistant.md")
    knowledge_text = (ASSISTANT_DIR / "knowledge.md").read_text(encoding="utf-8")
    permitted = asum.knowledge_references(knowledge_text)
    units = asum.collect_units(REPO_ROOT)
    confirms, _ = asum.event_counts(REPO_ROOT, "confirmations", set(units))
    flags, _ = asum.event_counts(REPO_ROOT, "flags", set(units))
    import json

    constants = json.loads((REPO_ROOT / ".cq" / "scoring.values.json").read_text(encoding="utf-8"))[
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


mcp = FastMCP("cq_assistant_mcp")


@mcp.tool(
    name="cq_assistant_get_profile",
    annotations={
        "title": "Get assistant profile",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def cq_assistant_get_profile() -> str:
    """Return this assistant's identity and instructions, meant to be used as its system prompt.

    Returns:
        str: Markdown with id, description, language, knowledge/flag policy and
        the `# Instructions` section from assistant.md.
    """
    state = _load_assistant()
    fm = state["frontmatter"]
    lines = [
        f"# {fm.get('id', ASSISTANT_SLUG)}",
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
    return "\n".join(lines)


@mcp.tool(
    name="cq_assistant_list_knowledge",
    annotations={
        "title": "List assistant's permitted knowledge units",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def cq_assistant_list_knowledge() -> str:
    """List every knowledge unit this assistant is allowed to cite, with current confidence.

    Confidence is computed at read time from confirmation/flag events, never stored.

    Returns:
        str: Markdown table with columns id, confidence, description. A KU id
        listed in knowledge.md that no longer exists in units/ is shown with
        confidence "missing" so gaps are visible instead of silently dropped.
    """
    state = _load_assistant()
    lines = ["| id | confidence | description |", "|---|---|---|"]
    for ku_id in state["permitted"]:
        if ku_id not in state["units"]:
            lines.append(f"| `{ku_id}` | missing | _knowledge unit not found in units/_ |")
            continue
        fm, _body = state["units"][ku_id]
        lines.append(f"| `{ku_id}` | {_confidence(state, ku_id):.2f} | {fm.get('description', '')} |")
    return "\n".join(lines)


class SearchKnowledgeInput(BaseModel):
    """Input model for searching this assistant's permitted knowledge."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    query: str = Field(..., description="Free-text search terms, e.g. 'refund webhook idempotency'", min_length=1, max_length=200)


@mcp.tool(
    name="cq_assistant_search_knowledge",
    annotations={
        "title": "Search assistant's permitted knowledge",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def cq_assistant_search_knowledge(params: SearchKnowledgeInput) -> str:
    """Search only within this assistant's permitted knowledge units (never the whole repo).

    Matches query tokens against each KU's description, Insight and Action
    text, case-insensitively. This is a simple relevance filter over an
    already-small, pre-approved set — not a substitute for the repo-wide
    BM25 index described in the README.

    Args:
        params (SearchKnowledgeInput): Validated input containing:
            - query (str): free-text search terms

    Returns:
        str: Markdown list of matching KUs ranked by token overlap, each with
        id, description and confidence. "No matches" message if none found.
    """
    state = _load_assistant()
    terms = [t for t in params.query.lower().split() if t]
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
        return f"No matches for '{params.query}' in this assistant's permitted knowledge."
    scored.sort(key=lambda row: row[0], reverse=True)
    lines = [f"# Matches for '{params.query}'", ""]
    for score, ku_id, fm in scored:
        lines.append(f"## `{ku_id}` (score {score})")
        lines.append(f"\n{fm.get('description', '')}")
        lines.append(f"\nConfidence: {_confidence(state, ku_id):.2f}\n")
    return "\n".join(lines)


class GetKnowledgeInput(BaseModel):
    """Input model for fetching one permitted knowledge unit in full."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    ku_id: str = Field(..., description="Exact knowledge unit id, e.g. 'ku_a1b2c3d4e5f60718293a4b5c6d7e8f90'")


@mcp.tool(
    name="cq_assistant_get_knowledge",
    annotations={
        "title": "Get one permitted knowledge unit",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def cq_assistant_get_knowledge(params: GetKnowledgeInput) -> str:
    """Fetch the full Insight/Action/Citations of one knowledge unit this assistant may cite.

    Enforces the assistant's contract: refuses ids outside knowledge.md, and
    under `cited_only` refuses KUs without a usable `# Citations` link — the
    same rule scripts/validate.py checks in CI, re-checked here at read time.

    Args:
        params (GetKnowledgeInput): Validated input containing:
            - ku_id (str): exact KU id to fetch

    Returns:
        str: Markdown with description, confidence, Insight, Action and
        Citations. "Error: ..." string if the id is out of scope, missing,
        or fails the citation policy.
    """
    state = _load_assistant()
    ku_id = params.ku_id
    if ku_id not in state["permitted"]:
        return f"Error: `{ku_id}` is not in this assistant's knowledge.md — out of scope."
    if ku_id not in state["units"]:
        return f"Error: `{ku_id}` is listed in knowledge.md but does not exist in units/."
    fm, body = state["units"][ku_id]
    citations = asum.section(body, "Citations")
    if state["frontmatter"].get("knowledge_policy") == "cited_only" and not validate.has_usable_citation(body):
        return f"Error: `{ku_id}` has no usable citation, required by this assistant's cited_only policy."
    lines = [
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
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
