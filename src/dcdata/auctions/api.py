"""Thin client for https://api.creditfixings.com/api. [Work package C]"""

from __future__ import annotations

from ..http import Fetcher


class CreditFixingsAPI:
    def __init__(self, fetcher: Fetcher, refresh: bool = False):
        self.fetcher = fetcher
        self.refresh = refresh

    def years(self) -> list[int]:
        raise NotImplementedError

    def by_year(self, year: int) -> list[dict]:
        raise NotImplementedError

    def results_by_ticker(self, ticker: str) -> dict | None:
        raise NotImplementedError

    def details_by_id(self, auction_id: int | str) -> dict | None:
        raise NotImplementedError
