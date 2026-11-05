"""Scrape all CDS auctions with final prices -> auctions.csv. [Work package C]"""

from __future__ import annotations

from ..config import Settings
from ..http import Fetcher


def run_auctions(settings: Settings, fetcher: Fetcher, years: list[int] | None = None) -> dict:
    """Write settings.output_dir / 'auctions.csv'; return a summary dict of counts."""
    raise NotImplementedError
