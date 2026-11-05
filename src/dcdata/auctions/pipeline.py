"""Scrape all CDS auctions with final prices -> auctions.csv. [Work package C]"""

from __future__ import annotations

import logging
from collections import Counter
from urllib.parse import quote

from .. import config, csvio, schemas
from ..config import Settings
from ..http import Fetcher
from .api import CreditFixingsAPI

log = logging.getLogger(__name__)

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
    sp = (detail or {}).get("stateParams")
    return sp if isinstance(sp, dict) else {}


def _has_final_price(sp: dict) -> bool:
    return _strip(sp.get(FINAL_PRICE)) != ""


def _sort_key(row: dict) -> tuple[str, int]:
    return row["auction_date"], int(row["auction_id"])


def run_auctions(settings: Settings, fetcher: Fetcher, years: list[int] | None = None) -> dict:
    """Write settings.output_dir / 'auctions.csv'; return a summary dict of counts."""
    api = CreditFixingsAPI(fetcher, refresh=settings.refresh)

    available = set(api.years())
    wanted = sorted(available)
    if years:
        requested = {int(y) for y in years}
        wanted = sorted(available & requested)
        if missing := sorted(requested - available):
            log.warning("Requested years not offered by the API: %s", missing)
    log.info("Fetching auction lists for %d years: %s", len(wanted), wanted)

    auctions: dict[int, dict] = {}
    n_lcds = 0
    n_dupes = 0
    for y in wanted:
        items = api.by_year(y)
        log.info("Year %d: %d auctions listed", y, len(items))
        for a in items:
            if _strip(a.get("auctionType")).upper() == "LCDS":
                n_lcds += 1
                continue
            aid = int(a["auctionID"])
            if aid in auctions:
                n_dupes += 1
                log.warning("Duplicate auctionID %s (year %d); keeping the first", aid, y)
                continue
            auctions[aid] = a
    log.info("Dropped %d LCDS auctions; %d CDS auctions remain", n_lcds, len(auctions))

    # One results call per distinct (raw) ticker; tickers may differ only by whitespace.
    tickers = sorted({a.get("ticker") or "" for a in auctions.values()})
    results: dict[str, tuple[dict | None, int | None]] = {}
    for i, t in enumerate(tickers, 1):
        log.info("Results %d/%d: ticker %r", i, len(tickers), t)
        results[t] = api.results_by_ticker(t) if t.strip() else (None, None)

    rows = []
    statuses: Counter[str] = Counter()
    for aid, a in auctions.items():
        ticker = a.get("ticker") or ""
        res, res_code = results[ticker]
        detail_map = (res or {}).get("auctionDetailsMap") or {}
        sp = _state_params(detail_map.get(str(aid)))

        det_code = None
        if not _has_final_price(sp):
            log.info("Auction %s (%r): no final price in results, trying details", aid, ticker)
            detail, det_code = api.details_by_id(aid)
            fallback = _state_params(detail)
            if _has_final_price(fallback) or not sp:
                sp = fallback or sp

        if _has_final_price(sp):
            status = "ok"
        else:
            if res is None and res_code is not None and det_code is not None:
                status = f"http_{res_code}"
            else:
                status = "missing_final_price"
            log.warning("Auction %s (%r): %s", aid, ticker, status)
        statuses[status] += 1

        rows.append(
            {
                "auction_id": aid,
                "auction_year": _value(a.get("auctionYear")),
                "auction_date": _value(a.get("auctionDate"))[:10],
                "legal_name": _strip(a.get("legalName")),
                "short_name": _strip(a.get("shortName")),
                "ticker": ticker.strip(),
                "auction_type": _strip(a.get("auctionType")),
                "tier": _strip(a.get("tier")),
                "tenor": _strip(a.get("tenor")),
                "ccy": _strip(a.get("CCY")),
                "dc_region": _strip(a.get("dcRegion")),
                "isda_link": _value(a.get("isdaLink")),
                "final_price": _value(sp.get(FINAL_PRICE)),
                "initial_market_midpoint": _value(sp.get(MIDPOINT)),
                "auction_status": _value(sp.get(STATUS)),
                "results_url": config.CF_RESULTS_UI.format(ticker=quote(ticker, safe="")),
                "results_fetch_status": status,
            }
        )

    rows.sort(key=_sort_key)
    out = settings.output_dir / "auctions.csv"
    n = csvio.write_csv(rows, out, schemas.AUCTIONS_COLUMNS)
    summary = {
        "n_auctions": n,
        "n_lcds_dropped": n_lcds,
        "n_duplicates_dropped": n_dupes,
        "n_with_final_price": statuses.get("ok", 0),
        "statuses": dict(sorted(statuses.items())),
    }
    log.info("Wrote %d auctions to %s: %s", n, out, summary)
    return summary
