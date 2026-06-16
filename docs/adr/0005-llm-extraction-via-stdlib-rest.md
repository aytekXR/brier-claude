# ADR-0005: LLM extraction via stdlib REST (no litellm SDK)

- **Status:** accepted (ratified 2026-06-16, launch-readiness ADR gate; no dependency — live activation pending the production `BRIER_ANTHROPIC_API_KEY`. CI/dev stays mock-first via the FakeExtractor.)
- **Date:** 2026-06-14 (proposed); 2026-06-16 (accepted)
- **Deciders:** human owner (approved 2026-06-16) + pipeline-engineer (E3-T1)

## Context

Task E3-T1 (FR-201) implements pass-1 candidate prediction detection in
transcripts. PRD §18 names **LiteLLM** as the provider router for extraction
("Haiku-class for both extraction passes with structured outputs; Sonnet-class
for arbitration; LiteLLM router; provider-swappable in config").

The stack is **locked** (CLAUDE.md "Boring stack, locked"): no new dependency
lands without human approval **and** an ADR. The `litellm` package pulls in a
large dependency tree (openai, anthropic SDK, httpx, and others) that would
change the CI install footprint and require ongoing maintenance.

A direct precedent exists from E2-T4: the Deepgram transcription adapter
(ADR-0003) was implemented as a stdlib-REST call (`POST
https://api.deepgram.com/v1/listen` via `urllib.request` + `json`) rather than
adding the Deepgram SDK. The same approach applies here. The Anthropic Messages
API (`POST https://api.anthropic.com/v1/messages`) is a plain JSON REST endpoint
that requires only three headers and a JSON body — no SDK is needed to drive it.

The `completion()` seam is designed so that the provider-routing role LiteLLM
would play (model aliases, retries, failover) can be added later by swapping the
transport implementation behind the same signature, without reshaping the call
sites in `LlmExtractor`.

**Recorded fixtures are the CI/eval substrate.** No API key and no network path
are needed in CI. `LlmExtractor` accepts an injectable `completion` callable;
tests supply recorded Anthropic response dicts from `data/fixtures/llm/`. The
default callable (`llm.completion`) raises a clear `RuntimeError` mentioning
`BRIER_ANTHROPIC_API_KEY` when the key is absent, which is the expected
behaviour in CI.

## Decision (proposed)

Implement the `completion()` seam in `brier_pipeline/extraction/llm.py` using
only stdlib `urllib.request` and `json`:

- A single `completion(model_name, messages, *, system=None, max_tokens=1024)`
  function POSTs to `https://api.anthropic.com/v1/messages` with the
  `x-api-key`, `anthropic-version: 2023-06-01`, and `content-type:
  application/json` headers. Key from `config.anthropic_api_key()`
  (`BRIER_ANTHROPIC_API_KEY` env var).
- If the key is empty the function raises `RuntimeError` with a clear message
  pointing to `BRIER_ANTHROPIC_API_KEY` and this ADR. This is the CI path:
  tests never reach the network.
- `LlmExtractor` injects the callable; production uses the default
  `llm.completion`; tests inject a fake returning recorded fixture dicts.
- No `litellm`, `anthropic`, `openai`, or any other third-party package is
  imported anywhere in the pipeline.
- Nothing is added to `[project.dependencies]` or any
  `[project.optional-dependencies]` extra in `pyproject.toml`.

If/when the human owner approves adding the LiteLLM SDK, the transport swap is:
replace the body of `llm.completion` (or the default injected callable) with a
LiteLLM router call. No call-site changes required.

## Structured-output convention

PRD §18 specifies "structured outputs" for the Haiku-class extraction passes.
Anthropic's Messages API supports structured/tool-use output modes, but these
require SDK or carefully hand-crafted request bodies that are more complex than
plain text responses. As a proposed substitute, this ADR adopts a
**JSON-in-text** convention: the model is instructed via the system and user
prompts to return a specific JSON schema embedded in its text content block
(e.g. `{"candidates": [{"index": <int>, "text": "<verbatim>"}]}`), and
`_parse_pass1_response` parses that text. This achieves the same structured
result without native tool-use wiring. When/if the LiteLLM SDK is approved
(ADR-0001 gate), the transport can be swapped to use proper structured outputs
or tool-use behind the same `completion()` seam — no call-site changes in
`LlmExtractor` are required. The E3-T1 definition of done is satisfied by this
JSON-in-text approach; the checkbox is unambiguous.

## Consequences

- Zero new install-time dependencies. CI and dev are unaffected.
- The `completion()` signature is provider-neutral; a LiteLLM SDK swap is a
  single-function change behind the existing seam (no reshape of
  `LlmExtractor`).
- Recorded fixtures in `data/fixtures/llm/` are the CI substrate; they also
  serve as the eval input for the golden-set harness (E3-T6).
- Until approved, the seam calls Anthropic directly; provider failover and model
  aliases are manual config. The LiteLLM router would add those automatically,
  which is the motivation for eventual approval.
- Spend is subject to the NFR-5 hard monthly caps (E6-T4). The seam is UNUSED
  in CI; real spend only occurs in the extraction pipeline on the production host.
- **Accepted 2026-06-16** at the launch-readiness ADR gate. No `litellm`/`anthropic`
  SDK is added (stdlib REST only); the only remaining step is setting
  `BRIER_ANTHROPIC_API_KEY` on the production extraction host. CI/dev stays
  mock-first via the `FakeExtractor`.
