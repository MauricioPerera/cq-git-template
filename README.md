# cq-git — Shared agent knowledge, on git

> 🌐 **[Visual guide (ES · EN · PT)](https://mauricioperera.github.io/cq-git-template/)** — how it works, for technical and non-technical readers.

## An open, git-native alternative to Custom GPTs

A [Custom GPT](https://openai.com/index/introducing-gpts/) bundles three
things behind a closed platform: a system prompt, a fixed knowledge base, and
whatever access control OpenAI gives you. This repo builds the same three
things as plain, auditable Git:

| | Custom GPT | Here |
|---|---|---|
| System prompt | Locked in OpenAI's UI | [`assistants/<slug>/assistant.md`](assistants/soporte-stripe/assistant.md) — a Markdown file, reviewed by PR |
| Knowledge base | Uploaded files, opaque retrieval | [`units/`](units/) — versioned KUs with provenance, confidence, and required citations |
| Access scope | Whatever the platform allows | `knowledge.md` — an explicit allow-list of KU ids per assistant, enforced by [`scripts/validate.py`](scripts/validate.py) and at runtime by [`scripts/assistant_mcp_server.py`](scripts/assistant_mcp_server.py) |
| Runtime | OpenAI's servers, any LLM they choose | Bring your own: connect the MCP server to an agent, use the CLI directly, or run `assistant_run.py` end-to-end against any model the [Antigravity CLI](https://antigravity.google) exposes (Gemini, Claude, GPT-OSS) |

No vendor lock-in, no black-box retrieval: every fact an assistant can cite
has a file, a diff, an author, and a confidence score computed from
confirm/flag events — never just "trust the upload." See
[**Usar un asistente**](#usar-un-asistente-sin-conocimientos-técnicos) to
define one and [**Serve one assistant as a scoped MCP server**](#serve-one-assistant-as-a-scoped-mcp-server)
to connect it to an agent.

The rest of this README documents the underlying commons — the knowledge
storage layer that makes assistants auditable instead of another opaque
upload.

## The underlying commons

Template for a git-based agent knowledge commons: knowledge units (KUs) stored as
[OKF v0.1](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)-conformant
markdown files, with the dynamic protocol of [cq](https://github.com/mozilla-ai/cq)
(propose / confirm / flag / scoring) mapped onto plain git primitives.

**One invariant governs everything: files are the source of truth; everything
derived (confidence, indexes, ranking) is computed at read time and never
committed.** That is why git never has merge conflicts over mutable state.

## Layout

```
.
├── index.md                     # OKF root index (declares okf_version)
├── units/                       # one .md file per knowledge unit
│   └── <domain>/<slug>.md       # grouping is navigational only — the ID lives in frontmatter
├── events/                      # append-only; one file = one event; never edited or deleted
│   ├── confirmations/<ku_id>/<timestamp>_<rand>.md
│   └── flags/<ku_id>/<timestamp>_<rand>.md
├── assistants/                  # versioned assistant definitions
│   └── <slug>/
│       ├── assistant.md         # identity, policies and instructions
│       └── knowledge.md         # explicit list of allowed KU ids
├── .cq/
│   ├── remotes.yaml             # upstream repos and their tier / write policy
│   └── scoring.values.json      # scoring constants (same values as cq)
├── scripts/
│   ├── validate.py              # conformance + integrity checks (used by CI)
│   ├── confidence.py            # derived confidence table, computed from events
│   ├── assistant_summary.py     # readable, derived view of one assistant
│   ├── assistant_mcp_server.py  # MCP server scoped to one assistant
│   ├── assistant_cli.py         # terminal/CI equivalent, no MCP dependency
│   ├── assistant_run.py         # end-to-end: question -> scoped prompt -> agy CLI answer
│   └── check_dedup.py           # near-duplicate detection for new KUs
└── .github/
    ├── CODEOWNERS               # human review = the HITL dashboard
    ├── pull_request_template.md # VIBE-style checklist for proposals
    └── workflows/
        ├── validate.yaml        # schema + integrity + secret scan + dedup warn
        └── auto-merge-events.yaml  # auto-merges PRs that only add event files
```

## The protocol, in git terms

| cq operation | Here |
|---|---|
| `propose` | PR adding one file under `units/`. Requires human review (CODEOWNERS). |
| `confirm` | PR adding one file under `events/confirmations/<ku_id>/`. Auto-merged when CI passes. |
| `flag`    | PR adding one file under `events/flags/<ku_id>/`. Auto-merged when CI passes. |
| confidence | Never stored. `clamp(0.5 + 0.1·confirmations − 0.15·flags, 0, 1)`, computed by `scripts/confidence.py` (or by a consuming MCP server) from the event files. |
| graduation | PR carrying the KU file (and optionally its events) to the upstream repo. The origin keeps its copy — nomination, not move. |
| provenance | `git log` / `git blame` / signed commits. The commit author *is* the event author. |
| review dashboard | The pull request itself. The diff is the review card. |

## Knowledge unit format

Every KU is an OKF concept document (`type` is the only OKF-required key) with
cq's fields in frontmatter and the tripartite insight in the body:

```markdown
---
type: KnowledgeUnit
id: ku_<32 hex>                  # stable identity across repos and renames
description: <one-line summary — this is insight.summary>
domains: [<tag>, ...]            # required, ≥1
languages: []                    # optional
frameworks: []                   # optional
pattern: <optional cross-cutting concern>
timestamp: <ISO 8601>
superseded_by: null              # or another ku_ id
---

# Insight

<detail — why it matters, with enough context>

# Action

<what to do about it, imperative>

# Citations

[1] [source](https://...)
```

See [units/api/stripe/rate-limit-200-body.md](units/api/stripe/rate-limit-200-body.md)
for a complete example, and its confirmation event under
[events/confirmations/](events/confirmations/).

Generate an id with: `python -c "import uuid; print('ku_' + uuid.uuid4().hex)"`

## Event format

```markdown
---
type: Confirmation               # or Flag
unit: ku_<32 hex>                # must exist in this repo
timestamp: <ISO 8601>
# Flag only:
reason: stale                    # stale | incorrect | duplicate
duplicate_of: ku_<32 hex>        # required iff reason == duplicate
---

Optional one-line context ("verified against docs 2026-07").
```

Filename: `<YYYY-MM-DDTHH-MM-SSZ>_<4 hex>.md` (dashes in the time part — colons
are not valid in filenames on all platforms). The parent directory name must
equal the `unit` field. Events for KUs that live in an upstream repo are
proposed to *that* repo, not recorded here.

## Setting up a shared (team / commons) repo

1. Create a repo from this template. Delete the example KU and event, keep the layout.
2. Edit `.github/CODEOWNERS`: point `/units/` at your reviewer team.
3. Branch protection on `main`: require PRs, require the `validate` status check,
   require Code Owner review. Files under `events/` have no code owner, so
   event-only PRs need no human review — that is deliberate.
4. The `auto-merge-events` workflow approves and auto-merges event-only PRs that
   pass validation. It needs `Allow auto-merge` enabled in repo settings.
5. Fill `.cq/remotes.yaml` in *downstream* clones to point at this repo.

## Local validation

```
python scripts/validate.py            # conformance + integrity (exit 1 on errors)
python scripts/confidence.py          # derived confidence table for all KUs
python scripts/check_dedup.py --all   # pairwise near-duplicate report
```

Only dependency: `pyyaml`.

## Usar un asistente (sin conocimientos técnicos)

Un asistente es una definición revisable en Git: describe su propósito, sus
instrucciones y exactamente qué unidades de conocimiento puede consultar. No
incluye un chat ni se conecta a ningún proveedor de IA.

Para ver el asistente de ejemplo, abre
[`assistants/soporte-stripe/assistant.md`](assistants/soporte-stripe/assistant.md).
Su archivo `knowledge.md` enumera las KUs permitidas mediante IDs exactos en
backticks o elementos de lista Markdown. El validador comprueba esa estructura,
el índice de asistentes y, con la política `cited_only`, que cada KU tenga una
sección `# Citations` con al menos un enlace Markdown utilizable. Para comprobar
los archivos y vínculos, ejecuta desde la carpeta del repositorio:

```console
python scripts/validate.py
```

Para obtener una ficha legible con la identidad, instrucciones, descripción,
citas y confianza actual de cada KU vinculada, ejecuta:

```console
python scripts/assistant_summary.py . soporte-stripe
```

La confianza se calcula al momento desde confirmaciones, flags y
`.cq/scoring.values.json`; la ficha no modifica ni guarda ningún dato. Para
crear otro asistente, copia la carpeta de ejemplo, asigna un `id` único que
empiece por `assistant_`, usa un código de idioma BCP-47 simple (por ejemplo,
`es` o `en-US`), edita las instrucciones, añade su enlace a
`assistants/index.md` y lista al menos un ID de KU existente en `knowledge.md`.

## Serve one assistant as a scoped MCP server

The generic MCP below serves the whole `units/` commons unscoped — any agent
can search any KU. `scripts/assistant_mcp_server.py` instead serves exactly
one `assistants/<slug>/` definition: its `# Instructions` as a system prompt,
and only the KU ids listed in that assistant's `knowledge.md` — enforcing
`cited_only` at read time, not just in CI.

Extra dependency beyond `pyyaml`: `pip install mcp`.

```bash
CQ_ASSISTANT_SLUG=soporte-stripe python scripts/assistant_mcp_server.py
```

Tools exposed: `cq_assistant_get_profile`, `cq_assistant_list_knowledge`,
`cq_assistant_search_knowledge`, `cq_assistant_get_knowledge` — the last one
refuses any `ku_id` outside `knowledge.md` and any KU missing a usable
citation under `cited_only`.

To connect it to Claude Code, add to `.mcp.json` in the repo root:

```json
{
  "mcpServers": {
    "cq-assistant-soporte-stripe": {
      "command": "python",
      "args": ["scripts/assistant_mcp_server.py"],
      "env": { "CQ_ASSISTANT_SLUG": "soporte-stripe" }
    }
  }
}
```

One MCP server = one assistant. To serve another assistant, add another
entry with its own `CQ_ASSISTANT_SLUG`.

### CLI alternative (no MCP dependency)

For a human at a terminal, or a script/CI step, `scripts/assistant_cli.py`
exposes the same four operations without speaking MCP — only dependency is
`pyyaml`, same as the rest of `scripts/`:

```console
python scripts/assistant_cli.py . soporte-stripe profile
python scripts/assistant_cli.py . soporte-stripe list
python scripts/assistant_cli.py . soporte-stripe search rate limit 200
python scripts/assistant_cli.py . soporte-stripe get ku_a1b2c3d4e5f60718293a4b5c6d7e8f90
```

Same scoping rules as the MCP server: refuses ids outside `knowledge.md` and
KUs without a usable citation under `cited_only`.

### Running the assistant end-to-end with a real model

`scripts/assistant_run.py` is the missing runtime piece: it takes a
question, uses the same scoping as the CLI/MCP to find matching permitted
KUs, assembles a prompt (instructions + full KU content), and hands it to
the [Antigravity CLI](https://antigravity.google) (`agy -p`) to get a real
answer — no LLM call happens if no permitted KU matches the question.

Requires `agy` on PATH and an authenticated session (`agy -p "hi"` should
just print a reply).

```console
python scripts/assistant_run.py . soporte-stripe -- "¿Por qué se nos pierden errores de Stripe bajo carga?"
```

`--model` (default `Gemini 3.5 Flash (Medium)`, see `agy models` for others)
and `--top` (max KUs included as context, default 3) are configurable.

## Consume the commons as verified MCP tools

Because KUs are OKF markdown, the whole commons can be published as a
serverless, hash-verified RAG that **any MCP agent can search** — no server,
no vector DB:

```bash
# once, in the repo root (regenerate when units/ changes; both are CI-checkable)
npx -y @rckflr/llms-skills memory units
npx -y @rckflr/llms-skills publish
```

That emits a BM25 snapshot of every KU pinned by SHA-256 in `llms.txt`, plus
three executable skills (`search_knowledge` / `get_concept` /
`list_concepts`). Any consumer turns the repo into an MCP server in one
command:

```bash
npx -y @rckflr/mcpwasm --serve . --port 8080     # local clone
# or, with the repo on GitHub Pages at a root site: npx -y @rckflr/mcpwasm <origin>
```

The runtime re-verifies every byte against the declared hashes before loading
anything, and runs each skill in a QuickJS-WebAssembly sandbox — so agents
query the shared knowledge with integrity guarantees, not just availability.
See [llms-txt-skills](https://mauricioperera.github.io/llms-txt-skills/) and
[mcpwasm](https://mauricioperera.github.io/mcpwasm/).

Optional extra ring: [signed knowledge freshness](https://github.com/MauricioPerera/llms-txt-skills/tree/master/cli#knowledge-freshness-freshness--attest)
(`llms-skills freshness units` / `attest`) — KUs already carry `timestamp`,
so TTL checks work out of the box, and a signed attestation is the
cryptographic upgrade of a cq `confirm`: a registered reviewer signs
"still true", bound to the KU's exact content (voided by any edit — the
`superseded_by` semantics) and expiring on a date.

## Conformance

Bundles produced by this template are OKF v0.1 conformant: every non-reserved
`.md` file has parseable YAML frontmatter with a non-empty `type`; `index.md`
follows the OKF index structure. Any generic OKF consumer (Obsidian, MkDocs,
graph viewers) can browse the repo without understanding cq semantics.

## License

[Apache-2.0](LICENSE). Note that knowledge contributions may warrant a
contributor agreement distinct from the code license — see cq's
`CONTRIBUTOR_AGREEMENT.md` for a model.
