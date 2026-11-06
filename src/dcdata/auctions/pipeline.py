"""The ``auctions`` step: scrape every CDS auction with its final price -> auctions.csv.

Per year the API lists auctions; the Final Price lives in a separate per-ticker results call, with a
per-auction details call as fallback. Each auction row records how that went in ``results_fetch_status``.
"""

from __future__ import annotations

import logging
from collections import Counter
from urllib.parse import quote

from .. import config, csvio, schemas
from ..config import Settings
from ..http import Fetcher
from .api import CreditFixingsAPI

log = logging.getLogger(__name__)

# Keys of the ``stateParams`` object in the results / details payloads.
FINAL_PRICE = "Final Price"
MIDPOINT = "Initial Market Midpoint"
STATUS = "Auction Status"


def _value(v) -> str:
    """Render an API value as text without altering strings or adding float noise."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, float):
        return repr(v)  # shortest round-trip representation
    return str(v)


def _strip(v) -> str:
    return _value(v).strip()


def _state_params(detail: dict | None) -> dict:
    """The ``stateParams`` dict (Final Price, midpoint, status) of one auction's payload, else {}."""
    params = (detail or {}).get("stateParams")
    return params if isinstance(params, dict) else {}


def _has_final_price(state_params: dict) -> bool:
    return _strip(state_params.get(FINAL_PRICE)) != ""


def _sort_key(row: dict) -> tuple[str, int]:
    return row["auction_date"], int(row["auction_id"])


def _select_years(api: CreditFixingsAPI, years: list[int] | None) -> list[int]:
    """The years to fetch: all the API offers, or the requested ones among them."""
    available = set(api.years())
    if not years:
        return sorted(available)
    requested = {int(y) for y in years}
    if missing := sorted(requested - available):
        log.warning("Requested years not offered by the API: %s", missing)
    return sorted(available & requested)


def _list_cds_auctions(api: CreditFixingsAPI, years: list[int]) -> tuple[dict[int, dict], int, int]:
    """``(auctions by auctionID, n_lcds_dropped, n_duplicates_dropped)`` over the given years.
    LCDS (loan-only) auctions are dropped; for a repeated auctionID the first listing wins."""
    auctions: dict[int, dict] = {}
    n_lcds = 0
    n_dupes = 0
    for year in years:
        listed = api.by_year(year)
        log.info("Year %d: %d auctions listed", year, len(listed))
        for auction in listed:
            if _strip(auction.get("auctionType")).upper() == "LCDS":
                n_lcds += 1
                continue
            auction_id = int(auction["auctionID"])
            if auction_id in auctions:
                n_dupes += 1
                log.warning("Duplicate auctionID %s (year %d); keeping the first", auction_id, year)
                continue
            auctions[auction_id] = auction
    log.info("Dropped %d LCDS auctions; %d CDS auctions remain", n_lcds, len(auctions))
    return auctions, n_lcds, n_dupes


def _fetch_results(
    api: CreditFixingsAPI, auctions: dict[int, dict]
) -> dict[str, tuple[dict | None, int | None]]:
    """Raw ticker -> ``api.results_by_ticker`` outcome, one call per distinct ticker.
    Tickers may differ only by whitespace, so they are keyed verbatim; a blank ticker gets no call."""
    tickers = sorted({a.get("ticker") or "" for a in auctions.values()})
    results: dict[str, tuple[dict | None, int | None]] = {}
    for i, ticker in enumerate(tickers, 1):
        log.info("Results %d/%d: ticker %r", i, len(tickers), ticker)
        results[ticker] = api.results_by_ticker(ticker) if ticker.strip() else (None, None)
    return results


def _find_final_price(
    api: CreditFixingsAPI,
    auction_id: int,
    ticker: str,
    ticker_results: tuple[dict | None, int | None],
) -> tuple[dict, str]:
    """``(state_params, results_fetch_status)`` for one auction.

    Looks in the ticker's results first and falls back to the auction's details call when the
    results carry no Final Price. Status: ``ok``, ``http_<code>`` (results and details both
    failed), or ``missing_final_price``."""
    results, results_status = ticker_results
    details_by_auction = (results or {}).get("auctionDetailsMap") or {}
    state_params = _state_params(details_by_auction.get(str(auction_id)))

    details_status = None
    if not _has_final_price(state_params):
        log.info("Auction %s (%r): no final price in results, trying details", auction_id, ticker)
        details, details_status = api.details_by_id(auction_id)
        fallback = _state_params(details)
        if _has_final_price(fallback) or not state_params:
            state_params = fallback or state_params

    if _has_final_price(state_params):
        return state_params, "ok"
    if results is None and results_status is not None and details_status is not None:
        status = f"http_{results_status}"
    else:
        status = "missing_final_price"
    log.warning("Auction %s (%r): %s", auction_id, ticker, status)
    return state_params, status


def _auction_row(auction_id: int, auction: dict, state_params: dict, status: str) -> dict:
    """One auctions.csv row from the listing entry plus its ``stateParams``."""
    ticker = auction.get("ticker") or ""
    return {
        "auction_id": auction_id,
        "auction_year": _value(auction.get("auctionYear")),
        "auction_date": _value(auction.get("auctionDate"))[:10],
        "legal_name": _strip(auction.get("legalName")),
        "short_name": _strip(auction.get("shortName")),
        "ticker": ticker.strip(),
        "auction_type": _strip(auction.get("auctionType")),
        "tier": _strip(auction.get("tier")),
        "tenor": _strip(auction.get("tenor")),
        "ccy": _strip(auction.get("CCY")),
        "dc_region": _strip(auction.get("dcRegion")),
        "isda_link": _value(auction.get("isdaLink")),
        "final_price": _value(state_params.get(FINAL_PRICE)),
        "initial_market_midpoint": _value(state_params.get(MIDPOINT)),
        "auction_status": _value(state_params.get(STATUS)),
        "results_url": config.CF_RESULTS_UI.format(ticker=quote(ticker, safe="")),
        "results_fetch_status": status,
    }


def run_auctions(settings: Settings, fetcher: Fetcher, years: list[int] | None = None) -> dict:
    """Write settings.output_dir / 'auctions.csv'; return a summary dict of counts."""
    api = CreditFixingsAPI(fetcher, refresh=settings.refresh)

    wanted_years = _select_years(api, years)
    log.info("Fetching auction lists for %d years: %s", len(wanted_years), wanted_years)
    auctions, n_lcds, n_dupes = _list_cds_auctions(api, wanted_years)
    results_by_ticker = _fetch_results(api, auctions)

    rows = []
    statuses: Counter[str] = Counter()
    for auction_id, auction in auctions.items():
        ticker = auction.get("ticker") or ""
        state_params, status = _find_final_price(api, auction_id, ticker, results_by_ticker[ticker])
        statuses[status] += 1
        rows.append(_auction_row(auction_id, auction, state_params, status))

    rows.sort(key=_sort_key)
    out_path = settings.output_dir / "auctions.csv"
    n_rows = csvio.write_csv(rows, out_path, schemas.AUCTIONS_COLUMNS)
    summary = {
        "n_auctions": n_rows,
        "n_lcds_dropped": n_lcds,
        "n_duplicates_dropped": n_dupes,
        "n_with_final_price": statuses.get("ok", 0),
        "statuses": dict(sorted(statuses.items())),
    }
    log.info("Wrote %d auctions to %s: %s", n_rows, out_path, summary)
    return summary
