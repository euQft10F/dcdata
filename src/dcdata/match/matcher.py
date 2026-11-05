"""Auction -> DC credit event matching. [Work package D]"""

from __future__ import annotations


def match_auctions(
    auctions: list[dict],
    events: list[dict],
    documents: list[dict],
    scorer: str = "token_sort_ratio",
    threshold: float = 80.0,
    date_window: tuple[int, int] = (-7, 365),
) -> list[dict]:
    """One dict per auction with schemas.MATCHES_COLUMNS."""
    raise NotImplementedError
