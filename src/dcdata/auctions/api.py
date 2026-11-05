"""Thin client for https://api.creditfixings.com/api. [Work package C]

Tickers are used exactly as the API gives them: some carry a leading space (``" MONTE"``)
and are distinct from their unspaced namesake (``"MONTE"``), so they are never stripped here.
"""

from __future__ import annotations

import logging
from urllib.parse import quote

from .. import config
from ..http import Fetcher

log = logging.getLogger(__name__)

HEADERS = {
    "Origin": config.CF_ORIGIN,
    "Accept": "application/json",
    "Referer": config.CF_ORIGIN + "/",
}


def safe_key(value: str | int) -> str:
    """Filesystem-safe, collision-free cache-key component (percent-encoding)."""
    s = quote(str(value), safe="")
    if s.startswith("."):  # avoid ".", ".." and hidden files
        s = "%2E" + s[1:]
    return s


class CreditFixingsAPI:
    def __init__(self, fetcher: Fetcher, refresh: bool = False):
        self.fetcher = fetcher
        self.refresh = refresh

    def _get(self, path: str, cache_key: str):
        url = f"{config.CF_API}/{path}"
        return url, self.fetcher.get(url, cache_key=cache_key, refresh=self.refresh, headers=HEADERS)

    def _get_required(self, path: str, cache_key: str):
        url, res = self._get(path, cache_key)
        if not res.ok:
            raise RuntimeError(f"HTTP {res.status} for {url}")
        return res.json()

    def _get_optional(self, path: str, cache_key: str) -> tuple[dict | None, int | None]:
        """``(data, None)`` on success, ``(None, http_status)`` on a non-2xx response."""
        url, res = self._get(path, cache_key)
        if not res.ok:
            log.warning("HTTP %s for %s", res.status, url)
            return None, res.status
        data = res.json()
        return (data if isinstance(data, dict) else None), None

    def years(self) -> list[int]:
        return [int(y) for y in self._get_required("auctions/years", "cf/years.json")]

    def by_year(self, year: int) -> list[dict]:
        year = int(year)
        return list(self._get_required(f"auctions/year/{year}", f"cf/year_{year}.json") or [])

    def results_by_ticker(self, ticker: str) -> tuple[dict | None, int | None]:
        return self._get_optional(
            f"auction-results/{quote(ticker, safe='')}", f"cf/results_{safe_key(ticker)}.json"
        )

    def details_by_id(self, auction_id: int | str) -> tuple[dict | None, int | None]:
        return self._get_optional(
            f"auction-details/{quote(str(auction_id), safe='')}",
            f"cf/details_{safe_key(auction_id)}.json",
        )
