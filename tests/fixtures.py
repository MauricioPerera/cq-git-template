"""Shared temp-repo fixture for assistant CLI/MCP server tests."""

from __future__ import annotations

import json
from pathlib import Path

SLUG = "test-assistant"
KU_ID = "ku_0123456789abcdef0123456789abcdef"          # no citations
CITED_KU_ID = "ku_fedcba9876543210fedcba9876543210"     # has citations


def build_repo(root: Path) -> None:
    """Populate root with one assistant (cited_only) permitting one cited and
    one uncited KU, plus the scoring config both scripts need."""
    units_dir = root / "units"
    units_dir.mkdir(parents=True)
    (units_dir / "uncited.md").write_text(
        f"---\ntype: KnowledgeUnit\nid: {KU_ID}\n"
        "description: Stripe rate limit returns 200 with an error body\n"
        "domains: [api]\ntimestamp: 2026-01-01T00:00:00Z\n---\n\n"
        "# Insight\n\nStripe rate-limit quirk.\n\n# Action\n\nCheck the response body.\n",
        encoding="utf-8",
    )
    (units_dir / "cited.md").write_text(
        f"---\ntype: KnowledgeUnit\nid: {CITED_KU_ID}\n"
        "description: Webhook retries are idempotent\n"
        "domains: [api]\ntimestamp: 2026-01-01T00:00:00Z\n---\n\n"
        "# Insight\n\nWebhook retry idempotency.\n\n# Action\n\nUse the idempotency key.\n\n"
        "# Citations\n\n[1] [Stripe docs](https://stripe.com/docs)\n",
        encoding="utf-8",
    )

    assistant_dir = root / "assistants" / SLUG
    assistant_dir.mkdir(parents=True)
    (assistant_dir / "assistant.md").write_text(
        "---\ntype: Assistant\nid: assistant_test\ndescription: test assistant\n"
        "language: es\nknowledge_policy: cited_only\nflag_policy: warn\n---\n\n"
        "# Instructions\n\nBe concise.\n",
        encoding="utf-8",
    )
    (assistant_dir / "knowledge.md").write_text(
        f"# Knowledge\n\n- `{CITED_KU_ID}`\n- `{KU_ID}`\n", encoding="utf-8"
    )

    cq_dir = root / ".cq"
    cq_dir.mkdir(parents=True)
    (cq_dir / "scoring.values.json").write_text(
        json.dumps(
            {
                "relevance_weights": {"domain": 0.55, "language": 0.15, "framework": 0.15, "pattern": 0.15},
                "confidence_constants": {
                    "initial": 0.5,
                    "confirmation_boost": 0.1,
                    "flag_penalty": 0.15,
                    "ceiling": 1.0,
                    "floor": 0.0,
                },
            }
        ),
        encoding="utf-8",
    )
