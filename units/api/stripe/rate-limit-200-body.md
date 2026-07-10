---
type: KnowledgeUnit
id: ku_a1b2c3d4e5f60718293a4b5c6d7e8f90
description: Stripe returns HTTP 200 with an error body for rate-limited requests.
domains: [api, payments, stripe]
languages: [python, typescript]
frameworks: []
pattern: api-integration
timestamp: 2026-07-10T14:00:00Z
superseded_by: null
---

# Insight

Stripe API v2024-12 returns HTTP 200 with a JSON `error` object in the response
body for rate-limited requests, instead of the expected 429 status code. Code
that treats any 2xx as success silently drops these errors and typically only
fails under load.

# Action

Parse the response body and check for an `error` field before treating any 2xx
response as success. Verify current behavior against the Stripe API changelog
before relying on this.

# Citations

[1] [Stripe API changelog](https://stripe.com/docs/changelog)
