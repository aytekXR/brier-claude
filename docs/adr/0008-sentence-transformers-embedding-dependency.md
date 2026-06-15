# ADR-0008: sentence-transformers as an optional embedding dependency

- **Status:** proposed (pending human approval)
- **Date:** 2026-06-15
- **Deciders:** human owner (approval pending) + pipeline-engineer (proposing, E3-T5)

## Context

Task E3-T5 (FR-205, EC-2) implements semantic claim deduplication.  The
`claims.embedding vector(384)` column already exists in Postgres (migration
`0003_claims.sql`; pgvector enabled in `0001_extensions.sql`).  No new
migration is needed.

FR-205 requires embedding each claim's `quote` text into a 384-dim vector for
cosine-similarity grouping via pgvector.  The stack is **locked** (CLAUDE.md
"Boring stack, locked"): no new dependency without human approval **and** an
ADR.

The only embedding model that produces 384-dim vectors with no additional
infrastructure is **`all-MiniLM-L6-v2`** from the `sentence-transformers`
library (HuggingFace).  The model is 80 MB; `sentence-transformers` pulls in
PyTorch.  It cannot be reduced to a stdlib call.

Per the E2/E3 ADR-gate precedent (ADR-0003, ADR-0004), the
`SentenceTransformerEmbedder` adapter is landed as a **seam**:

- The `Embedder` ABC (`extraction/embeddings.py`) defines the interface.
- `SentenceTransformerEmbedder.embed()` lazily imports `sentence_transformers`
  INSIDE the method body (never at module load time), so the package is not
  required at import time.
- When the package is absent, a clear `RuntimeError` is raised that names the
  package, the ADR, and the installation command — not a silent `ImportError`.
- `HashEmbedder` — a deterministic, dependency-free fake built on SHA-256 — is
  the CI/dev/test path.  Tests inject it via the `embedder=` parameter on
  `dedup_claims`.  No model download, no network, no inference in any test.

## Decision (proposed)

Add `sentence-transformers` (pinned) as an **optional extra**, not a core
dependency:

```
[project.optional-dependencies]
embed = ["sentence-transformers==<pinned>"]
```

- Installed only on the host(s) running `dedup_claims` in production; never in
  CI or dev.
- `SentenceTransformerEmbedder._load()` lazily imports `sentence_transformers`
  inside the method body (never at module load time); absent the extra it raises
  a clear, actionable `RuntimeError` naming the package and this ADR.
- `HashEmbedder` stays the fixture/CI/test path; no test downloads a model or
  makes a network call.
- The mypy override (`[[tool.mypy.overrides]] module = ["sentence_transformers"]
  ignore_missing_imports = true`) suppresses type-check errors for the absent
  package without needing per-line suppression comments.

## Clustering algorithm

`dedup_claims` uses **representative-linkage** clustering:

1. Claims are processed in ascending `uttered_at` order within each
   `(analyst_id, asset, direction)` group.
2. The first claim in a group seeds a new cluster and becomes its
   **representative** (the earliest-uttered member, per EC-2).
3. Each subsequent claim is compared **only against existing representatives**
   (never against intermediate members of a cluster).  A claim joins a cluster
   when both conditions hold:
   - cosine similarity with the representative ≥ `similarity_threshold`, AND
   - the candidate's horizon window overlaps the representative's horizon window
     (FR-205: "overlapping horizon" is a property of the claim pair being
     compared, not of any chain of intermediates).
4. If no representative qualifies, the claim seeds a new cluster.

This eliminates transitive horizon-bridging: a chain A[Jan-Mar] → B[Mar-Jun] →
C[Jun-Sep] with identical vectors does NOT let C land in A's cluster, because
C is compared directly against A (the representative), and their horizons do not
overlap.

## Similarity computation paths

**DB path** (`conn` provided — production use):

Embeddings are written to `claims.embedding vector(384)` and the pgvector
`<=>` cosine-distance operator is used to find the nearest representative:

```sql
SELECT id, (embedding <=> %s::vector) AS dist
FROM claims WHERE id = ANY(%s)
ORDER BY dist ASC LIMIT 1
```

Similarity = `1 - dist`.  The horizon-overlap check and threshold comparison
are applied in Python after the query.  This is the FR-205 / §18 production
path: "via pgvector embeddings."

**In-memory path** (`conn=None` — tests and offline use):

A pure Python `_cosine_similarity` function computes the dot-product cosine
over the in-process embedding vectors.  No DB is required; this path is used
in all CI tests.

## Consequences

- Semantic dedup becomes real once the extra is installed on the relevant host;
  CI and dev are unaffected (the extra is never installed there).
- The `vector(384)` column and pgvector `<=>` operator are already in place
  (migrations `0001_extensions.sql`, `0003_claims.sql`); approval only flips
  package installation on — no code reshape, no migration.
- Model weights (80 MB) are downloaded on first use of `SentenceTransformerEmbedder`
  and cached by the HuggingFace library; the pipeline host must have outbound
  network access on first run.
- **This ADR is not yet accepted.**  Until the human owner approves, the `embed`
  extra is not added to `pyproject.toml` and `sentence-transformers` is not
  installed.  Changing this requires the owner's approval recorded here (status
  → accepted) per ADR-0001 and CLAUDE.md.
