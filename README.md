# cq-git — Shared agent knowledge, on git

> 🌐 **[Visual guide (ES · EN · PT)](https://mauricioperera.github.io/cq-git-template/)** — how it works, for technical and non-technical readers.

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
├── .cq/
│   ├── remotes.yaml             # upstream repos and their tier / write policy
│   └── scoring.values.json      # scoring constants (same values as cq)
├── scripts/
│   ├── validate.py              # conformance + integrity checks (used by CI)
│   ├── confidence.py            # derived confidence table, computed from events
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
