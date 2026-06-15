"""E3-T5 semantic dedup tests (FR-205, EC-2).

Categories:
  1. Pure in-memory dedup tests — no DB; inject HashEmbedder for deterministic
     vectors; assert cluster assignment, grouping guards, EC-2 timestamp ordering.
  2. DB-backed tests via db_conn (rolled-back) — embeddings and dedup_cluster_ids
     are written to real claim rows; pgvector column receives the vector.
  3. Seam test — SentenceTransformerEmbedder.embed() raises RuntimeError (with
     ADR-0008 mention) because sentence-transformers is absent in CI.
"""

from __future__ import annotations

import math
from datetime import UTC, date, datetime
from typing import Any, Literal

import pytest

from brier_pipeline.extraction.embeddings import HashEmbedder, SentenceTransformerEmbedder
from brier_pipeline.extraction.extractor import dedup_claims
from brier_pipeline.models import Claim, SpecificityClass

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_claim(
    *,
    analyst_id: int = 1,
    video_id: int = 1,
    transcript_id: int = 1,
    asset: str | None = "BTC",
    direction: Literal["bullish", "bearish"] | None = "bullish",
    horizon_deadline: date | None = date(2025, 12, 31),
    uttered_at: datetime = datetime(2025, 1, 1, tzinfo=UTC),
    quote: str = "BTC will hit 100k by year end",
    claim_id: int | None = None,
) -> Claim:
    return Claim(
        id=claim_id,
        analyst_id=analyst_id,
        video_id=video_id,
        transcript_id=transcript_id,
        asset=asset,
        direction=direction,
        horizon_deadline=horizon_deadline,
        horizon_basis="stated" if horizon_deadline else None,
        specificity_class=SpecificityClass.DIRECTION_ONLY,
        source_offset_seconds=0,
        model_version="test-v0",
        prompt_version="test-v0",
        uttered_at=uttered_at,
        quote=quote,
    )


def _unit_vector(dim: int, index: int) -> list[float]:
    """Return a 384-dim unit vector with 1.0 at position index, 0.0 elsewhere."""
    assert 0 <= index < dim
    v = [0.0] * dim
    v[index] = 1.0
    return v


def _scaled_vector(base: list[float], noise_index: int, noise: float) -> list[float]:
    """Add a small noise component to a unit vector, then re-normalise."""
    v = list(base)
    v[noise_index] = noise
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v]


# ---------------------------------------------------------------------------
# 1. Pure in-memory tests (no DB)
# ---------------------------------------------------------------------------


class TestDedupInMemory:
    """Pure dedup logic tested with injected embedder (no DB)."""

    def test_empty_input_returns_empty(self) -> None:
        """dedup_claims([]) must return [] without raising (smoke-test guard)."""
        result = dedup_claims([], embedder=HashEmbedder())
        assert result == []

    def test_single_claim_gets_own_cluster(self) -> None:
        """A single claim forms its own cluster (cluster_id = its list index)."""
        claim = _make_claim()
        result = dedup_claims([claim], embedder=HashEmbedder())
        assert len(result) == 1
        assert result[0].dedup_cluster_id is not None

    def test_near_duplicate_claims_share_cluster(self) -> None:
        """Two claims with cosine sim >= threshold share the same cluster id."""
        # Use identical quotes → identical HashEmbedder vectors → cosine sim = 1.0.
        quote = "BTC will definitely reach one hundred thousand this year"
        claim_a = _make_claim(quote=quote, uttered_at=datetime(2025, 1, 1, tzinfo=UTC))
        claim_b = _make_claim(quote=quote, uttered_at=datetime(2025, 3, 1, tzinfo=UTC))

        result = dedup_claims([claim_a, claim_b], embedder=HashEmbedder())

        assert result[0].dedup_cluster_id == result[1].dedup_cluster_id

    def test_semantically_different_claims_get_separate_clusters(self) -> None:
        """Claims with low cosine similarity must be in distinct clusters.

        We inject two orthogonal unit vectors via a custom fake embedder.
        """

        class OrthogonalEmbedder(HashEmbedder):
            """Returns alternating orthogonal unit vectors based on call order."""

            def __init__(self) -> None:
                self._call_count = 0

            def embed(self, text: str) -> list[float]:
                vec = _unit_vector(384, self._call_count % 2)
                self._call_count += 1
                return vec

        claim_a = _make_claim(
            quote="BTC will be bullish",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        claim_b = _make_claim(
            quote="something completely different",
            uttered_at=datetime(2025, 2, 1, tzinfo=UTC),
        )

        result = dedup_claims([claim_a, claim_b], embedder=OrthogonalEmbedder())

        # Cosine similarity between orthogonal unit vectors is 0.0 < 0.9.
        assert result[0].dedup_cluster_id != result[1].dedup_cluster_id

    def test_different_asset_not_clustered(self) -> None:
        """Claims on different assets must NOT cluster even with identical quotes."""
        quote = "will reach new highs this year"
        claim_btc = _make_claim(asset="BTC", quote=quote)
        claim_eth = _make_claim(asset="ETH", quote=quote)

        result = dedup_claims([claim_btc, claim_eth], embedder=HashEmbedder())

        assert result[0].dedup_cluster_id != result[1].dedup_cluster_id

    def test_different_direction_not_clustered(self) -> None:
        """Claims with opposite directions must NOT cluster."""
        quote = "BTC one hundred thousand by year end"
        claim_bull = _make_claim(direction="bullish", quote=quote)
        claim_bear = _make_claim(direction="bearish", quote=quote)

        result = dedup_claims([claim_bull, claim_bear], embedder=HashEmbedder())

        assert result[0].dedup_cluster_id != result[1].dedup_cluster_id

    def test_non_overlapping_horizon_not_clustered(self) -> None:
        """Claims with non-overlapping horizons must NOT cluster."""
        quote = "BTC will be bullish"
        # Claim A: horizon ends 2025-03-31, uttered Jan 1
        claim_a = _make_claim(
            quote=quote,
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 3, 31),
        )
        # Claim B: uttered after A's deadline, horizon 2025-06-30
        claim_b = _make_claim(
            quote=quote,
            uttered_at=datetime(2025, 4, 1, tzinfo=UTC),
            horizon_deadline=date(2025, 6, 30),
        )
        # Intervals [Jan1, Mar31] and [Apr1, Jun30] do NOT overlap.
        result = dedup_claims([claim_a, claim_b], embedder=HashEmbedder())

        assert result[0].dedup_cluster_id != result[1].dedup_cluster_id

    def test_different_analyst_not_clustered(self) -> None:
        """Claims from different analysts must NOT cluster even with identical quotes."""
        quote = "BTC will be massive"
        claim_a = _make_claim(analyst_id=1, quote=quote)
        claim_b = _make_claim(analyst_id=2, quote=quote)

        result = dedup_claims([claim_a, claim_b], embedder=HashEmbedder())

        assert result[0].dedup_cluster_id != result[1].dedup_cluster_id

    def test_ec2_reupload_preserves_earliest_timestamp(self) -> None:
        """EC-2: when a re-upload joins an existing cluster, the cluster id points
        to the EARLIEST uttered claim, not the re-upload.
        """
        quote = "BTC one hundred thousand by year end confirmed"

        # Original claim (earlier).
        original = _make_claim(
            quote=quote,
            uttered_at=datetime(2025, 1, 10, tzinfo=UTC),
            claim_id=101,
        )
        # Re-upload: same content, later timestamp.
        reupload = _make_claim(
            quote=quote,
            uttered_at=datetime(2025, 6, 1, tzinfo=UTC),
            claim_id=102,
        )

        # Original first so it seeds the cluster; re-upload joins.
        result = dedup_claims([original, reupload], embedder=HashEmbedder())

        assert result[0].dedup_cluster_id == result[1].dedup_cluster_id
        # Cluster id = DB id of the EARLIEST claim (original).
        assert result[0].dedup_cluster_id == original.id
        assert result[1].dedup_cluster_id == original.id

    def test_ec2_reupload_joins_even_when_processed_first(self) -> None:
        """EC-2: even if the re-upload appears first in the list, the cluster id
        still points to the earliest-uttered claim (the original).
        """
        quote = "ETH five thousand dollars soon"

        original = _make_claim(
            asset="ETH",
            direction="bullish",
            quote=quote,
            uttered_at=datetime(2025, 2, 1, tzinfo=UTC),
            claim_id=201,
        )
        reupload = _make_claim(
            asset="ETH",
            direction="bullish",
            quote=quote,
            uttered_at=datetime(2025, 9, 1, tzinfo=UTC),
            claim_id=202,
        )

        # Pass re-upload first in the list; implementation must sort by uttered_at.
        result = dedup_claims([reupload, original], embedder=HashEmbedder())

        assert result[0].dedup_cluster_id == result[1].dedup_cluster_id
        # Both cluster ids must equal the original's id (earliest uttered).
        cluster_id = result[0].dedup_cluster_id
        assert cluster_id == original.id

    def test_similarity_threshold_respected(self) -> None:
        """A vector just below the threshold must NOT join the cluster."""

        class ControlledEmbedder(HashEmbedder):
            """Returns pre-computed vectors keyed on text."""

            def __init__(self, vectors: dict[str, list[float]]) -> None:
                self._vectors = vectors

            def embed(self, text: str) -> list[float]:
                return self._vectors[text]

        # Two nearly-orthogonal vectors: cosine sim should be 0.0 (orthogonal).
        vec_a = _unit_vector(384, 0)  # [1, 0, 0, ...]
        vec_b = _unit_vector(384, 1)  # [0, 1, 0, ...]

        quote_a = "quote_a_text"
        quote_b = "quote_b_text"

        embedder = ControlledEmbedder({quote_a: vec_a, quote_b: vec_b})

        claim_a = _make_claim(quote=quote_a, uttered_at=datetime(2025, 1, 1, tzinfo=UTC))
        claim_b = _make_claim(quote=quote_b, uttered_at=datetime(2025, 2, 1, tzinfo=UTC))

        # Default threshold 0.9 — cosine sim 0.0 < 0.9 → separate clusters.
        result = dedup_claims([claim_a, claim_b], embedder=embedder)
        assert result[0].dedup_cluster_id != result[1].dedup_cluster_id

        # Reset cluster ids and run with threshold 0.0 — everything should cluster.
        claim_c = _make_claim(quote=quote_a, uttered_at=datetime(2025, 1, 1, tzinfo=UTC))
        claim_d = _make_claim(quote=quote_b, uttered_at=datetime(2025, 2, 1, tzinfo=UTC))
        result2 = dedup_claims(
            [claim_c, claim_d],
            embedder=embedder,
            similarity_threshold=0.0,
        )
        assert result2[0].dedup_cluster_id == result2[1].dedup_cluster_id


# ---------------------------------------------------------------------------
# 2. DB-backed tests (rolled-back via db_conn)
# ---------------------------------------------------------------------------


def _get_seeded_parent_ids(cur: Any) -> tuple[int, int, int]:
    """Return (analyst_id, video_id, transcript_id) from the seeded dev DB."""
    cur.execute("select id from analysts limit 1")
    a_row = cur.fetchone()
    assert a_row is not None, "No analysts seeded — run make seed first"
    analyst_id = int(a_row[0])

    cur.execute("select id from videos where analyst_id = %s limit 1", (analyst_id,))
    v_row = cur.fetchone()
    assert v_row is not None, "No videos seeded — run make seed first"
    video_id = int(v_row[0])

    cur.execute("select id from transcripts where video_id = %s limit 1", (video_id,))
    t_row = cur.fetchone()
    assert t_row is not None, "No transcripts seeded — run make seed first"
    transcript_id = int(t_row[0])

    return analyst_id, video_id, transcript_id


def _insert_claim_row(
    cur: Any,
    *,
    analyst_id: int,
    video_id: int,
    transcript_id: int,
    asset: str = "BTC",
    direction: str = "bullish",
    horizon_deadline: str = "2025-12-31",
    uttered_at: str = "2025-01-01 00:00:00+00",
    quote: str = "BTC will rise",
) -> int:
    """Insert a minimal claim row and return its id."""
    cur.execute(
        """
        insert into claims (
            analyst_id, video_id, transcript_id,
            asset, direction,
            horizon_deadline, horizon_basis,
            specificity_class, source_offset_seconds,
            quote, uttered_at,
            model_version, prompt_version,
            review_state, publishable, status, flags
        ) values (
            %s, %s, %s,
            %s, %s,
            %s, 'stated',
            'direction_only', 0,
            %s, %s,
            'test-v0', 'test-v0',
            'unreviewed', false, 'open', '{}'
        ) returning id
        """,
        (
            analyst_id,
            video_id,
            transcript_id,
            asset,
            direction,
            horizon_deadline,
            quote,
            uttered_at,
        ),
    )
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


class TestDedupWithDB:
    """DB-backed dedup: embeddings and cluster ids are written to real claim rows."""

    def test_near_duplicate_claims_share_cluster_in_db(self, db_conn: Any) -> None:
        """Two near-duplicate claims receive the same dedup_cluster_id in the DB."""
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_seeded_parent_ids(cur)
            quote = "BTC will absolutely hit one hundred thousand by year end no doubt"
            id_a = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                quote=quote,
                uttered_at="2025-01-01 00:00:00+00",
            )
            id_b = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                quote=quote,
                uttered_at="2025-06-01 00:00:00+00",
            )

        claim_a = _make_claim(
            claim_id=id_a, quote=quote, uttered_at=datetime(2025, 1, 1, tzinfo=UTC)
        )
        claim_b = _make_claim(
            claim_id=id_b, quote=quote, uttered_at=datetime(2025, 6, 1, tzinfo=UTC)
        )

        dedup_claims([claim_a, claim_b], embedder=HashEmbedder(), conn=db_conn)

        with db_conn.cursor() as cur:
            cur.execute(
                "select dedup_cluster_id, embedding is not null as has_embedding "
                "from claims where id = any(%s) order by id",
                ([id_a, id_b],),
            )
            rows = cur.fetchall()

        assert len(rows) == 2
        cluster_a, has_emb_a = rows[0]
        cluster_b, has_emb_b = rows[1]
        assert cluster_a == cluster_b, "Near-duplicate claims must share dedup_cluster_id"
        assert cluster_a == id_a, "Cluster id must be the earliest claim's DB id (EC-2)"
        assert has_emb_a, "Embedding must be written to DB for claim A"
        assert has_emb_b, "Embedding must be written to DB for claim B"

    def test_semantically_different_claims_get_separate_clusters_in_db(self, db_conn: Any) -> None:
        """Claims with orthogonal vectors get distinct cluster ids in the DB."""

        class OrthogonalEmbedder(HashEmbedder):
            def __init__(self) -> None:
                self._call_count = 0

            def embed(self, text: str) -> list[float]:
                vec = _unit_vector(384, self._call_count % 2)
                self._call_count += 1
                return vec

        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_seeded_parent_ids(cur)
            id_a = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                quote="alpha claim text",
                uttered_at="2025-01-01 00:00:00+00",
            )
            id_b = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                quote="beta claim text different",
                uttered_at="2025-02-01 00:00:00+00",
            )

        claim_a = _make_claim(
            claim_id=id_a,
            quote="alpha claim text",
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        claim_b = _make_claim(
            claim_id=id_b,
            quote="beta claim text different",
            uttered_at=datetime(2025, 2, 1, tzinfo=UTC),
        )

        dedup_claims([claim_a, claim_b], embedder=OrthogonalEmbedder(), conn=db_conn)

        with db_conn.cursor() as cur:
            cur.execute(
                "select dedup_cluster_id from claims where id = any(%s) order by id",
                ([id_a, id_b],),
            )
            rows = cur.fetchall()

        assert len(rows) == 2
        assert rows[0][0] != rows[1][0], "Orthogonal claims must get distinct cluster ids"

    def test_different_asset_not_clustered_in_db(self, db_conn: Any) -> None:
        """Claims on different assets are never clustered, even with identical vectors."""
        quote = "will hit new highs"
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_seeded_parent_ids(cur)
            id_btc = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                asset="BTC",
                quote=quote,
            )
            id_eth = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                asset="ETH",
                quote=quote,
            )

        claim_btc = _make_claim(claim_id=id_btc, asset="BTC", quote=quote)
        claim_eth = _make_claim(claim_id=id_eth, asset="ETH", quote=quote)

        dedup_claims([claim_btc, claim_eth], embedder=HashEmbedder(), conn=db_conn)

        with db_conn.cursor() as cur:
            cur.execute(
                "select dedup_cluster_id from claims where id = any(%s) order by id",
                ([id_btc, id_eth],),
            )
            rows = cur.fetchall()

        assert len(rows) == 2
        assert rows[0][0] != rows[1][0], "Different-asset claims must not share cluster id"

    def test_ec2_reupload_cluster_id_is_original_in_db(self, db_conn: Any) -> None:
        """EC-2: re-upload joins the cluster and cluster id = original claim's DB id."""
        quote = "SOL will be massive this year for sure"
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_seeded_parent_ids(cur)
            id_original = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                asset="SOL",
                direction="bullish",
                quote=quote,
                uttered_at="2025-01-15 10:00:00+00",
            )
            id_reupload = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                asset="SOL",
                direction="bullish",
                quote=quote,
                uttered_at="2025-08-20 10:00:00+00",
            )

        original_claim = _make_claim(
            claim_id=id_original,
            asset="SOL",
            direction="bullish",
            quote=quote,
            uttered_at=datetime(2025, 1, 15, 10, tzinfo=UTC),
        )
        reupload_claim = _make_claim(
            claim_id=id_reupload,
            asset="SOL",
            direction="bullish",
            quote=quote,
            uttered_at=datetime(2025, 8, 20, 10, tzinfo=UTC),
        )

        dedup_claims(
            [original_claim, reupload_claim],
            embedder=HashEmbedder(),
            conn=db_conn,
        )

        with db_conn.cursor() as cur:
            cur.execute(
                "select id, dedup_cluster_id from claims where id = any(%s) order by id",
                ([id_original, id_reupload],),
            )
            rows = cur.fetchall()

        assert len(rows) == 2
        _, cluster_orig = rows[0]
        _, cluster_reup = rows[1]
        assert cluster_orig == cluster_reup, "Re-upload must join original's cluster"
        assert cluster_orig == id_original, "Cluster id must be the original claim's DB id (EC-2)"

    def test_horizon_bridge_three_claims_db(self, db_conn: Any) -> None:
        """Representative-linkage: C must NOT bridge into A's cluster through B.

        A[Jan-Mar], B[Mar-Jun], C[Jun-Sep], same analyst/asset/direction,
        identical quotes (cosine sim = 1.0 via HashEmbedder).

        With old single-linkage: A-B overlap → share cluster; B-C overlap →
        C joins B's cluster → C wrongly lands in A's cluster (BLOCKER).

        With representative-linkage: A is the representative.  B is compared
        against A → horizons [Jan1,Mar31] and [Mar1,Jun30] overlap → B joins A's
        cluster.  C is compared against A (the representative) → horizons
        [Jan1,Mar31] and [Jun1,Sep30] do NOT overlap → C seeds its own cluster.
        """
        quote = "BTC will surge dramatically this quarter guaranteed"
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_seeded_parent_ids(cur)
            id_a = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                quote=quote,
                horizon_deadline="2025-03-31",
                uttered_at="2025-01-01 00:00:00+00",
            )
            id_b = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                quote=quote,
                horizon_deadline="2025-06-30",
                uttered_at="2025-03-01 00:00:00+00",
            )
            id_c = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                quote=quote,
                horizon_deadline="2025-09-30",
                uttered_at="2025-06-01 00:00:00+00",
            )

        claim_a = _make_claim(
            claim_id=id_a,
            quote=quote,
            horizon_deadline=date(2025, 3, 31),
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        claim_b = _make_claim(
            claim_id=id_b,
            quote=quote,
            horizon_deadline=date(2025, 6, 30),
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
        )
        claim_c = _make_claim(
            claim_id=id_c,
            quote=quote,
            horizon_deadline=date(2025, 9, 30),
            uttered_at=datetime(2025, 6, 1, tzinfo=UTC),
        )

        dedup_claims([claim_a, claim_b, claim_c], embedder=HashEmbedder(), conn=db_conn)

        with db_conn.cursor() as cur:
            cur.execute(
                "select id, dedup_cluster_id from claims where id = any(%s) order by id",
                ([id_a, id_b, id_c],),
            )
            rows = cur.fetchall()

        assert len(rows) == 3
        _, cluster_a = rows[0]
        _, cluster_b = rows[1]
        _, cluster_c = rows[2]

        assert cluster_a == cluster_b, "A and B horizons overlap → must share cluster"
        assert cluster_a == id_a, "Cluster id must be A's DB id (earliest, EC-2)"
        assert cluster_c != cluster_a, (
            "C horizons do not overlap A's (the representative) → C must be a separate cluster"
        )

    def test_pgvector_path_similarity_works(self, db_conn: Any) -> None:
        """pgvector <=> path: two near-identical claims cluster correctly via DB query.

        This exercises the DB-path similarity branch end-to-end: embeddings are
        written to claims.embedding, then the <=> query finds the nearest
        representative, and both claims land in the same cluster.
        """
        quote = "ETH will reach five thousand dollars before year end for certain"
        with db_conn.cursor() as cur:
            analyst_id, video_id, transcript_id = _get_seeded_parent_ids(cur)
            id_x = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                asset="ETH",
                direction="bullish",
                quote=quote,
                uttered_at="2025-02-01 00:00:00+00",
            )
            id_y = _insert_claim_row(
                cur,
                analyst_id=analyst_id,
                video_id=video_id,
                transcript_id=transcript_id,
                asset="ETH",
                direction="bullish",
                quote=quote,
                uttered_at="2025-04-01 00:00:00+00",
            )

        claim_x = _make_claim(
            claim_id=id_x,
            asset="ETH",
            direction="bullish",
            quote=quote,
            uttered_at=datetime(2025, 2, 1, tzinfo=UTC),
        )
        claim_y = _make_claim(
            claim_id=id_y,
            asset="ETH",
            direction="bullish",
            quote=quote,
            uttered_at=datetime(2025, 4, 1, tzinfo=UTC),
        )

        dedup_claims([claim_x, claim_y], embedder=HashEmbedder(), conn=db_conn)

        with db_conn.cursor() as cur:
            cur.execute(
                "select id, dedup_cluster_id, embedding is not null as has_emb "
                "from claims where id = any(%s) order by id",
                ([id_x, id_y],),
            )
            rows = cur.fetchall()

        assert len(rows) == 2
        _, cluster_x, has_emb_x = rows[0]
        _, cluster_y, has_emb_y = rows[1]
        assert has_emb_x, "Embedding must be written to DB (pgvector path)"
        assert has_emb_y, "Embedding must be written to DB (pgvector path)"
        assert cluster_x == cluster_y, (
            "Identical quotes → cosine sim 1.0 via pgvector <=> → must share cluster"
        )
        assert cluster_x == id_x, "Cluster id must be earliest claim's DB id (EC-2)"

    def test_horizon_bridge_three_claims_in_memory(self) -> None:
        """Representative-linkage horizon-bridge test on the in-memory path.

        A[Jan-Mar], B[Mar-Jun], C[Jun-Sep], identical vectors.
        A and B share a cluster; C is separate because C's horizon does not
        overlap A's (the representative), even though C overlaps B.
        """
        quote = "BTC will surge dramatically this quarter guaranteed"
        claim_a = _make_claim(
            quote=quote,
            horizon_deadline=date(2025, 3, 31),
            uttered_at=datetime(2025, 1, 1, tzinfo=UTC),
        )
        claim_b = _make_claim(
            quote=quote,
            horizon_deadline=date(2025, 6, 30),
            uttered_at=datetime(2025, 3, 1, tzinfo=UTC),
        )
        claim_c = _make_claim(
            quote=quote,
            horizon_deadline=date(2025, 9, 30),
            uttered_at=datetime(2025, 6, 1, tzinfo=UTC),
        )

        result = dedup_claims([claim_a, claim_b, claim_c], embedder=HashEmbedder())

        assert result[0].dedup_cluster_id == result[1].dedup_cluster_id, (
            "A and B horizons overlap → must share cluster"
        )
        assert result[2].dedup_cluster_id != result[0].dedup_cluster_id, (
            "C horizons do not overlap A's (the representative) → C must be separate"
        )


# ---------------------------------------------------------------------------
# 3. Seam test — SentenceTransformerEmbedder raises when package is absent
# ---------------------------------------------------------------------------


class TestSentenceTransformerSeam:
    """Prove the ADR-0008 gate: RuntimeError is raised when sentence-transformers
    is absent.  sentence-transformers is intentionally NOT installed in CI.
    """

    def test_raises_runtime_error_when_package_absent(self) -> None:
        """SentenceTransformerEmbedder.embed() must raise RuntimeError (not ImportError)
        and the message must mention 'sentence-transformers' and 'ADR-0008'.
        """
        embedder = SentenceTransformerEmbedder()
        with pytest.raises(RuntimeError) as exc_info:
            embedder.embed("any text")
        msg = str(exc_info.value)
        assert "sentence-transformers" in msg
        assert "ADR-0008" in msg
