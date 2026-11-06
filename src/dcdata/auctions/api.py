"""Thin client for https://api.creditfixings.com/api.

Tickers are used exactly as the API gives them: some carry a leading space (``" MONTE"``)
and are distinct from their unspaced namesake (``"MONTE"``), so they are never stripped here.
"""

from __future__ import annotations

import hashlib
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

# Pseudo HTTP status reported for a 2xx response whose body is not JSON.
NOT_JSON = 299


def safe_key(value: str | int) -> str:
    """Filesystem-safe, collision-free cache-key component (percent-encoding).

    Keys with lowercase letters get a hash suffix so they cannot collide with an upper-case
    namesake on case-insensitive file systems (Windows, macOS)."""
    s = quote(str(value), safe="")
    if s.startswith("."):  # avoid ".", ".." and hidden files
        s = "%2E" + s[1:]
    if s != s.upper():
        s += "~" + hashlib.sha1(str(value).encode("utf-8")).hexdigest()[:8]
    return s


class CreditFixingsAPI:
    """The four endpoints we read. ``years`` / ``by_year`` are required (they raise on failure);
    ``results_by_ticker`` / ``details_by_id`` are optional and return ``(data, None)`` on success
    or ``(None, http_status)`` on failure, so the caller can record the failure per auction."""

    def __init__(self, fetcher: Fetcher, refresh: bool = False):
        self.fetcher = fetcher
        self.refresh = refresh

    def _get(self, path: str, cache_key: str):
        """``(url, status, data)``; data is None unless the response is 2xx with a JSON body.
        A 2xx non-JSON body (e.g. a maintenance page) is evicted from the cache."""
        url = f"{config.CF_API}/{path}"
        response = self.fetcher.get(url, cache_key=cache_key, refresh=self.refresh, headers=HEADERS)
        if not response.ok:
            return url, response.status, None
        try:
            return url, response.status, response.json()
        except ValueError:
            self.fetcher.invalidate(cache_key)
            return url, NOT_JSON, None

    def _get_required(self, path: str, cache_key: str):
        """JSON body of ``path``; raises RuntimeError on any failure."""
        url, status, data = self._get(path, cache_key)
        if data is None:
            raise RuntimeError(f"HTTP {status} (or non-JSON body) for {url}")
        return data

    def _get_optional(self, path: str, cache_key: str) -> tuple[dict | None, int | None]:
        """``(data, None)`` on success, ``(None, status)`` on a non-2xx or non-JSON response."""
        url, status, data = self._get(path, cache_key)
        if data is None:
            log.warning("HTTP %s (or non-JSON body) for %s", status, url)
            return None, status
        return (data if isinstance(data, dict) else None), None

    def years(self) -> list[int]:
        """Years that have auctions."""
        return [int(y) for y in self._get_required("auctions/years", "cf/years.json")]

    def by_year(self, year: int) -> list[dict]:
        """Auction listing of one year (one dict per auction, CDS and LCDS)."""
        year = int(year)
        return list(self._get_required(f"auctions/year/{year}", f"cf/year_{year}.json") or [])

    def results_by_ticker(self, ticker: str) -> tuple[dict | None, int | None]:
        """Results of every auction of ``ticker`` (``auctionDetailsMap``, keyed by auction id)."""
        return self._get_optional(
            f"auction-results/{quote(ticker, safe='')}", f"cf/results_{safe_key(ticker)}.json"
        )

    def details_by_id(self, auction_id: int | str) -> tuple[dict | None, int | None]:
        """Details of a single auction; the fallback when the ticker results lack a Final Price."""
        return self._get_optional(
            f"auction-details/{quote(str(auction_id), safe='')}",
            f"cf/details_{safe_key(auction_id)}.json",
        )
