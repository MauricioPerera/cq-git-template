#!/usr/bin/env python3
"""Answer a question through an assistant's contract, using a real LLM as the brain.

Wires together what's already built: assistant_cli.py resolves the
assistant's instructions and its permitted, cited_only-checked knowledge;
this script assembles them into a prompt and hands it to the Antigravity
CLI (`agy -p`) to actually answer. If no permitted KU matches the question,
the LLM is never called — refusal is enforced here in code, not left to the
model's cooperation.

Requires the `agy` CLI (https://antigravity.google) on PATH and an
authenticated session (`agy -p "hi"` should print a reply with no prompts).

Usage:
  python scripts/assistant_run.py <repo-root> <slug> [--model MODEL] [--top N] -- <question...>
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import assistant_cli as cli

DEFAULT_MODEL = "Gemini 3.5 Flash (Medium)"
DEFAULT_TOP = 3


def build_prompt(state: dict, question: str, matches: list[tuple[int, str, dict]]) -> str:
    """Assemble instructions + full content of the matched KUs + the question.

    Only the KUs in `matches` are included — the model never sees anything
    outside what assistant_cli.search already scoped to knowledge.md.
    """
    fm = state["frontmatter"]
    lines = [
        "Sos un asistente definido por el siguiente contrato. Seguilo al pie de la letra.",
        "",
        "# Instructions",
        "",
        state["instructions"],
        "",
        f"(knowledge_policy: {fm.get('knowledge_policy', '')}, flag_policy: {fm.get('flag_policy', '')})",
        "",
        "# Knowledge units disponibles (las únicas que podés citar)",
    ]
    for _score, ku_id, _fm in matches:
        lines.append("")
        lines.append(cli.cmd_get(state, ku_id))
    lines += ["", "# Pregunta del usuario", "", question]
    return "\n".join(lines)


def run_agy(prompt: str, model: str) -> str:
    try:
        result = subprocess.run(
            ["agy", "-p", prompt, "--model", model],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=300,
        )
    except FileNotFoundError:
        return "Error: `agy` CLI not found on PATH. Install it from https://antigravity.google."
    if result.returncode != 0:
        return f"Error: agy exited with status {result.returncode}: {result.stderr.strip()}"
    return result.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", help="repo root")
    parser.add_argument("slug", help="assistant directory name under assistants/")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"agy model name (default: {DEFAULT_MODEL!r})")
    parser.add_argument("--top", type=int, default=DEFAULT_TOP, help=f"max KUs to include as context (default: {DEFAULT_TOP})")
    parser.add_argument("question", nargs="+", help="the user's question")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    state = cli._load_assistant(root, args.slug)
    question = " ".join(args.question)

    matches = cli.search(state, question)[: args.top]
    if not matches:
        print(
            "No hay ninguna unidad de conocimiento vinculada a este asistente que cubra "
            "esa pregunta, así que no puedo responder con conocimiento verificado."
        )
        return 0

    print(run_agy(build_prompt(state, question, matches), args.model))
    return 0


if __name__ == "__main__":
    sys.exit(main())
