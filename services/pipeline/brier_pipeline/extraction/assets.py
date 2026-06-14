"""Controlled crypto-asset vocabulary and alias resolver (EC-7, METHODOLOGY.md §1).

Crypto + YouTube scope only (PRD §4: no equities, forex, or macro claims).
Ambiguous slang ("alts", "altcoins", "the market", unknown tickers) resolve
to None per EC-7.  Canonical symbols are uppercase ticker strings.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Canonical asset set
# ---------------------------------------------------------------------------

CANONICAL_ASSETS: frozenset[str] = frozenset(
    {
        "BTC",
        "ETH",
        "SOL",
        "BNB",
        "XRP",
        "ADA",
        "AVAX",
        "DOT",
        "LINK",
        "MATIC",
        "DOGE",
        "LTC",
        "ATOM",
        "UNI",
        "NEAR",
        "APT",
        "ARB",
        "OP",
        "SUI",
        "INJ",
        "TIA",
        "SEI",
        "TON",
    }
)

# ---------------------------------------------------------------------------
# Alias → canonical map
# ---------------------------------------------------------------------------

_ALIAS_MAP: dict[str, str] = {
    # Bitcoin
    "bitcoin": "BTC",
    "btc": "BTC",
    "xbt": "BTC",
    # Ethereum
    "ethereum": "ETH",
    "ether": "ETH",
    "eth": "ETH",
    # Solana
    "solana": "SOL",
    "sol": "SOL",
    # BNB / Binance Smart Chain
    "bnb": "BNB",
    "binance coin": "BNB",
    "binancecoin": "BNB",
    # XRP / Ripple
    "xrp": "XRP",
    "ripple": "XRP",
    # Cardano
    "ada": "ADA",
    "cardano": "ADA",
    # Avalanche
    "avax": "AVAX",
    "avalanche": "AVAX",
    # Polkadot
    "dot": "DOT",
    "polkadot": "DOT",
    # Chainlink
    "link": "LINK",
    "chainlink": "LINK",
    # Polygon
    "matic": "MATIC",
    "polygon": "MATIC",
    # Dogecoin
    "doge": "DOGE",
    "dogecoin": "DOGE",
    # Litecoin
    "ltc": "LTC",
    "litecoin": "LTC",
    # Cosmos
    "atom": "ATOM",
    "cosmos": "ATOM",
    # Uniswap
    "uni": "UNI",
    "uniswap": "UNI",
    # NEAR Protocol
    "near": "NEAR",
    # Aptos
    "apt": "APT",
    "aptos": "APT",
    # Arbitrum
    "arb": "ARB",
    "arbitrum": "ARB",
    # Optimism
    "op": "OP",
    "optimism": "OP",
    # Sui
    "sui": "SUI",
    # Injective
    "inj": "INJ",
    "injective": "INJ",
    # Celestia
    "tia": "TIA",
    "celestia": "TIA",
    # Sei
    "sei": "SEI",
    # Toncoin
    "ton": "TON",
    "toncoin": "TON",
    "the open network": "TON",
}


def resolve_asset(raw: str | None) -> str | None:
    """Normalise a raw asset string to a canonical ticker symbol.

    Returns:
        The canonical symbol (e.g. ``"BTC"``) when the input resolves
        unambiguously, or ``None`` for unresolvable / ambiguous inputs
        (EC-7: slang baskets like "alts", "altcoins", "the market",
        unknown tickers, or ``None`` input).

    The function is case-insensitive and strips surrounding whitespace.
    """
    if raw is None:
        return None

    normalised = raw.strip().lower()
    if not normalised:
        return None

    # Direct alias lookup (handles lowercase canonical forms too)
    candidate = _ALIAS_MAP.get(normalised)
    if candidate is not None:
        return candidate

    # Uppercase form might itself be canonical
    upper = normalised.upper()
    if upper in CANONICAL_ASSETS:
        return upper

    # Unresolvable: ambiguous slang, baskets, unknown tickers → None (EC-7)
    return None
