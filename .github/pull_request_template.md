<!-- For event-only PRs (confirmations/flags) delete this template; CI is the gate. -->

## Knowledge unit proposal

**Summary of the insight:**

### Safety / quality checklist (VIBE)

- [ ] **Vulnerabilities** — no credentials, tokens, internal hostnames, PII, or
      identifiers that fingerprint a private system, in any field or tag.
- [ ] **Impact** — applying the `# Action` verbatim in an unrelated codebase
      cannot cause data loss or weaken security.
- [ ] **Biases** — not tied to a person/team/vendor unless load-bearing for the
      lesson; narrow evidence is not presented as universal.
- [ ] **Edge cases** — known conditions where this does not hold (OS, version,
      scale) are acknowledged in `# Insight`.

### Generalizability

- [ ] Organization-specific context stripped; the insight is useful outside the
      repo where it was discovered.
- [ ] Will still be correct in six months, or states how to verify freshness
      (principle + verification method over pinned versions).
- [ ] Searched existing units first — this is not a near-duplicate
      (`python scripts/check_dedup.py <file>`).
