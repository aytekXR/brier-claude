"""Unit tests for the controlled asset vocabulary + alias resolver (EC-7).

All tests are stdlib-only, no network, no API keys.
"""

from __future__ import annotations

from brier_pipeline.extraction.assets import CANONICAL_ASSETS, resolve_asset

# ---------------------------------------------------------------------------
# Happy path: known aliases resolve to canonical symbols
# ---------------------------------------------------------------------------


def test_bitcoin_aliases_resolve() -> None:
    """'bitcoin', 'btc', 'xbt' all resolve to BTC."""
    assert resolve_asset("bitcoin") == "BTC"
    assert resolve_asset("btc") == "BTC"
    assert resolve_asset("xbt") == "BTC"


def test_ethereum_aliases_resolve() -> None:
    """'ethereum', 'ether', 'eth' all resolve to ETH."""
    assert resolve_asset("ethereum") == "ETH"
    assert resolve_asset("ether") == "ETH"
    assert resolve_asset("eth") == "ETH"


def test_solana_aliases_resolve() -> None:
    """'solana', 'sol' resolve to SOL."""
    assert resolve_asset("solana") == "SOL"
    assert resolve_asset("sol") == "SOL"


def test_bnb_aliases_resolve() -> None:
    assert resolve_asset("bnb") == "BNB"
    assert resolve_asset("binance coin") == "BNB"


def test_xrp_aliases_resolve() -> None:
    assert resolve_asset("xrp") == "XRP"
    assert resolve_asset("ripple") == "XRP"


def test_cardano_aliases_resolve() -> None:
    assert resolve_asset("ada") == "ADA"
    assert resolve_asset("cardano") == "ADA"


def test_avalanche_aliases_resolve() -> None:
    assert resolve_asset("avax") == "AVAX"
    assert resolve_asset("avalanche") == "AVAX"


def test_polkadot_aliases_resolve() -> None:
    assert resolve_asset("dot") == "DOT"
    assert resolve_asset("polkadot") == "DOT"


def test_chainlink_aliases_resolve() -> None:
    assert resolve_asset("link") == "LINK"
    assert resolve_asset("chainlink") == "LINK"


# ---------------------------------------------------------------------------
# Case insensitivity + whitespace normalisation
# ---------------------------------------------------------------------------


def test_case_insensitive_resolution() -> None:
    """Resolution is case-insensitive."""
    assert resolve_asset("Bitcoin") == "BTC"
    assert resolve_asset("BITCOIN") == "BTC"
    assert resolve_asset("BiTcOiN") == "BTC"
    assert resolve_asset("ETH") == "ETH"
    assert resolve_asset("Eth") == "ETH"


def test_whitespace_stripping() -> None:
    """Leading/trailing whitespace is stripped before lookup."""
    assert resolve_asset("  bitcoin  ") == "BTC"
    assert resolve_asset("\teth\n") == "ETH"
    assert resolve_asset(" SOL ") == "SOL"


# ---------------------------------------------------------------------------
# EC-7: ambiguous slang and unknown tickers resolve to None
# ---------------------------------------------------------------------------


def test_alts_resolves_to_none() -> None:
    """'alts' and 'altcoins' are ambiguous baskets and must resolve to None (EC-7)."""
    assert resolve_asset("alts") is None
    assert resolve_asset("altcoins") is None
    assert resolve_asset("Altcoins") is None


def test_the_market_resolves_to_none() -> None:
    """'the market' and similar basket phrases resolve to None (EC-7)."""
    assert resolve_asset("the market") is None
    assert resolve_asset("crypto market") is None


def test_unknown_ticker_resolves_to_none() -> None:
    """Unknown tickers not in the controlled vocabulary resolve to None (EC-7)."""
    assert resolve_asset("UNKN") is None
    assert resolve_asset("FAKECOIN") is None
    assert resolve_asset("shitcoin") is None


def test_none_input_returns_none() -> None:
    """None input resolves to None."""
    assert resolve_asset(None) is None


def test_empty_string_returns_none() -> None:
    """Empty/whitespace-only string resolves to None."""
    assert resolve_asset("") is None
    assert resolve_asset("   ") is None


# ---------------------------------------------------------------------------
# Canonical set membership
# ---------------------------------------------------------------------------


def test_canonical_assets_are_uppercase() -> None:
    """All canonical symbols are uppercase strings."""
    for symbol in CANONICAL_ASSETS:
        assert symbol == symbol.upper(), f"Canonical symbol {symbol!r} is not uppercase"


def test_canonical_assets_nonempty() -> None:
    """The canonical set is non-empty."""
    assert len(CANONICAL_ASSETS) > 0


def test_all_canonical_assets_self_resolve() -> None:
    """Every canonical ticker resolves to itself."""
    for symbol in CANONICAL_ASSETS:
        result = resolve_asset(symbol)
        assert result == symbol, (
            f"Canonical symbol {symbol!r} did not self-resolve (got {result!r})"
        )
