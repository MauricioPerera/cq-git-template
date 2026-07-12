---
name: cq-assistant-runtime
description: Use one of this repo's versioned assistants (assistants/<slug>/) — get its profile, list/search/fetch its permitted knowledge, or answer a real question end-to-end with a live model. Use when the user asks to "usar el asistente", "consultar el conocimiento de <slug>", "probar el asistente contra una pregunta", or mentions assistant_cli.py / assistant_mcp_server.py / assistant_run.py / agy in this repo.
---

# cq-assistant-runtime

This repo defines "assistants" as Git-reviewed contracts under
`assistants/<slug>/` (`assistant.md` = identity + instructions,
`knowledge.md` = explicit allow-list of KU ids from `units/`). Three
interchangeable ways to use one exist — pick by what the task needs.

## Which tool to use

| Need | Tool |
|---|---|
| Quick read: identity, instructions, permitted KUs, or one KU's content | `scripts/assistant_cli.py` |
| Expose the assistant as MCP tools to an agent (this session or another) | `scripts/assistant_mcp_server.py` |
| Actually answer a user's question with a real model, grounded only in permitted KUs | `scripts/assistant_run.py` |

All three enforce the same rules: only KU ids listed in `knowledge.md` are
ever used, and under `knowledge_policy: cited_only` a KU without a usable
`# Citations` link is refused. Never bypass this by reading `units/`
directly when a slug is in scope — that's the whole point of the contract.

## Commands (run from the repo root; root arg is `.`)

```console
# identity + instructions (system prompt)
python scripts/assistant_cli.py . <slug> profile

# every permitted KU with live-computed confidence
python scripts/assistant_cli.py . <slug> list

# token-overlap search restricted to permitted KUs
python scripts/assistant_cli.py . <slug> search <terms...>

# one KU in full (Insight/Action/Citations); errors if out of scope or uncited
python scripts/assistant_cli.py . <slug> get <ku_id>

# end-to-end: question -> scoped prompt -> real model answer
python scripts/assistant_run.py . <slug> -- "<question>"
```

`assistant_run.py` needs the `agy` CLI (https://antigravity.google) on PATH
and an authenticated session — sanity check with `agy -p "hi"` first if
unsure. It defaults to `--model "Gemini 3.5 Flash (Medium)"`; list other
options with `agy models`. If no permitted KU matches the question, it
prints a refusal and never calls the model — don't try to work around that
by feeding it unrelated KUs "just to get an answer."

The MCP server (`scripts/assistant_mcp_server.py`) takes the slug via the
`CQ_ASSISTANT_SLUG` env var, not an argument — see `.mcp.json` in the repo
root for the wiring Claude Code uses.

## Example assistant

`soporte-stripe` (see `assistants/soporte-stripe/`) is the only assistant
in this repo today, scoped to one KU about Stripe's rate-limit quirk. Use
it to sanity-check any change to these scripts before trusting the result.
