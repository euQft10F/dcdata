import json
import re
from urllib.parse import unquote

import httpx
import pytest
import respx
from conftest import FIXTURES

from dcdata import config, csvio, schemas
from dcdata.auctions.api import CreditFixingsAPI, safe_key
from dcdata.auctions.pipeline import run_auctions
from dcdata.config import Settings
from dcdata.http import Fetcher

API = config.CF_API
FIXTURE_RESULTS = {"NFEFIN", "NRAMC"}


def _load(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeAPI:
    """respx routes serving the fixtures. Tickers without a results fixture get an empty
    results map (forcing the details fallback); details return a synthetic final price."""

    def __init__(self, mock, *, results_status=200, details_status=200, details_price="50.0"):
        self.results_status = results_status
        self.details_status = details_status
        self.details_price = details_price
        self.years = mock.get(f"{API}/auctions/years").mock(
            return_value=httpx.Response(200, json=_load("cf_years.json"))
        )
        self.year = mock.get(url__regex=rf"^{re.escape(API)}/auctions/year/(?P<y>\d+)$").mock(
            side_effect=self._year
        )
        self.results = mock.get(url__regex=rf"^{re.escape(API)}/auction-results/(?P<t>.+)$").mock(
            side_effect=self._results
        )
        self.details = mock.get(url__regex=rf"^{re.escape(API)}/auction-details/(?P<i>\d+)$").mock(
            side_effect=self._details
        )

    def _year(self, request, y):
        return httpx.Response(200, json=_load(f"cf_year_{y}.json"))

    def _results(self, request, t):
        t = unquote(t)
        if t in FIXTURE_RESULTS:
            return httpx.Response(200, json=_load(f"cf_results_{t}.json"))
        if self.results_status != 200:
            return httpx.Response(self.results_status)
        return httpx.Response(200, json={"auctions": [], "auctionDetailsMap": {}, "resultsNote": None})

    def _details(self, request, i):
        if self.details_status != 200:
            return httpx.Response(self.details_status)
        sp = {"Final Price": self.details_price, "Auction Status": "was held"} if self.details_price else None
        return httpx.Response(200, json={"auction": {"auctionID": int(i)}, "stateParams": sp})


def _settings(tmp_path):
    return Settings(data_dir=tmp_path / "data")


def _fetcher(s):
    return Fetcher(cache_dir=s.cache_dir, delay=0)


def _rows(s):
    return csvio.read_csv(s.output_dir / "auctions.csv")


@respx.mock
def test_api_headers_and_cache_keys(tmp_path):
    FakeAPI(respx.mock)
    f = Fetcher(cache_dir=tmp_path, delay=0)
    api = CreditFixingsAPI(f)
    assert api.years()[0] == 2026
    assert len(api.by_year(2026)) == len(_load("cf_year_2026.json"))
    assert (
        api.results_by_ticker("NFEFIN")[0]["auctionDetailsMap"]["9183"]["stateParams"]["Final Price"]
        == "26.625"
    )
    api.results_by_ticker(" MONTE")
    assert api.details_by_id(9183)[0]["stateParams"]["Final Price"] == "50.0"
    req = respx.calls[0].request
    assert req.headers["Origin"] == config.CF_ORIGIN
    assert req.headers["Accept"] == "application/json"
    assert respx.calls[3].request.url.raw_path.endswith(b"/auction-results/%20MONTE")
    for k in (
        "years.json",
        "year_2026.json",
        "results_NFEFIN.json",
        "results_%20MONTE.json",
        "details_9183.json",
    ):
        assert (tmp_path / "cf" / k).exists(), k
    assert safe_key(".ARGENT") == "%2EARGENT"
    assert safe_key("A/B:C") == "A%2FB%3AC"
    assert safe_key("Monte").lower() != safe_key("MONTE").lower()  # case-insensitive file systems


@respx.mock
def test_api_errors(tmp_path):
    respx.get(f"{API}/auctions/years").mock(return_value=httpx.Response(404))
    respx.get(f"{API}/auction-results/X").mock(return_value=httpx.Response(404))
    api = CreditFixingsAPI(Fetcher(delay=0))
    with pytest.raises(RuntimeError):
        api.years()
    assert api.results_by_ticker("X") == (None, 404)


@respx.mock
def test_full_run(tmp_path):
    fake = FakeAPI(respx.mock)
    s = _settings(tmp_path)
    summary = run_auctions(s, _fetcher(s))
    assert summary["n_auctions"] == 136
    assert summary["n_lcds_dropped"] == 19
    assert summary["n_with_final_price"] == 136
    assert summary["statuses"] == {"ok": 136}

    rows = _rows(s)
    assert list(rows[0].keys()) == schemas.AUCTIONS_COLUMNS
    assert [(r["auction_date"], int(r["auction_id"])) for r in rows] == sorted(
        (r["auction_date"], int(r["auction_id"])) for r in rows
    )
    by_id = {r["auction_id"]: r for r in rows}
    assert len(by_id) == 136

    nfe = by_id["9183"]
    assert nfe["final_price"] == "26.625"
    assert nfe["initial_market_midpoint"] == "25.625"
    assert nfe["auction_status"] == "was held"
    assert nfe["auction_date"] == "2026-01-14"
    assert nfe["results_url"] == "https://www.creditfixings.com/#/auction-results/NFEFIN"
    assert nfe["results_fetch_status"] == "ok"

    assert by_id["9032"]["final_price"] == "104.25"
    assert by_id["9032"]["tier"] == "Bucket 1"
    assert by_id["9036"]["final_price"] == "99.125"
    assert by_id["9036"]["tier"] == "Bucket 2"

    # LCDS dropped: FCGIA only appears as an LCDS auction in 2012.
    assert "FCGIA" not in {r["ticker"] for r in rows}
    assert {r["auction_type"] for r in rows} == {"CDS"}

    # Whitespace-prefixed tickers are distinct API keys: queried raw, written stripped.
    called = {unquote(c.request.url.raw_path.decode().rsplit("/", 1)[1]) for c in fake.results.calls}
    assert " MONTE" in called and "MONTE" in called
    assert fake.results.call_count == len(called)  # one call per distinct ticker
    monte = [r for r in rows if r["ticker"] == "MONTE"]
    assert any(r["results_url"].endswith("/%20MONTE") for r in monte)

    # Fallback used for every auction without a results fixture.
    n_fixture = sum(1 for r in rows if r["ticker"] in FIXTURE_RESULTS)
    assert fake.details.call_count == 136 - n_fixture
    assert {r["final_price"] for r in rows if r["ticker"] not in FIXTURE_RESULTS} == {"50.0"}


@respx.mock
def test_second_run_uses_cache(tmp_path):
    FakeAPI(respx.mock)
    s = _settings(tmp_path)
    run_auctions(s, _fetcher(s), years=[2026, 2012])
    first = (s.output_dir / "auctions.csv").read_bytes()
    n_calls = len(respx.calls)
    f2 = _fetcher(s)
    run_auctions(s, f2, years=[2026, 2012])
    assert f2.n_network_requests == 0
    assert len(respx.calls) == n_calls
    assert (s.output_dir / "auctions.csv").read_bytes() == first


@respx.mock
def test_years_filter(tmp_path):
    fake = FakeAPI(respx.mock)
    s = _settings(tmp_path)
    summary = run_auctions(s, _fetcher(s), years=[2026, 1999])
    assert fake.year.call_count == 1
    assert summary["n_auctions"] == len(_load("cf_year_2026.json"))
    assert {r["auction_year"] for r in _rows(s)} == {"2026"}


@respx.mock
def test_missing_final_price(tmp_path):
    FakeAPI(respx.mock, details_price=None)
    s = _settings(tmp_path)
    summary = run_auctions(s, _fetcher(s), years=[2012])
    rows = _rows(s)
    fixture_rows = [r for r in rows if r["ticker"] in FIXTURE_RESULTS]
    assert summary["statuses"] == {
        "missing_final_price": len(rows) - len(fixture_rows),
        "ok": len(fixture_rows),
    }
    assert all(r["final_price"] == "" for r in rows if r["results_fetch_status"] == "missing_final_price")


@respx.mock
def test_http_failure_status(tmp_path):
    FakeAPI(respx.mock, results_status=404, details_status=404)
    s = _settings(tmp_path)
    summary = run_auctions(s, _fetcher(s), years=[2026])
    rows = {r["auction_id"]: r for r in _rows(s)}
    assert rows["9183"]["results_fetch_status"] == "ok"  # NFEFIN served from fixture
    others = [r for r in rows.values() if r["ticker"] not in FIXTURE_RESULTS]
    assert others and all(r["results_fetch_status"] == "http_404" for r in others)
    assert summary["statuses"]["http_404"] == len(others)


@respx.mock
def test_numeric_final_price_rendering(tmp_path):
    FakeAPI(respx.mock, details_price=26.625)  # JSON number instead of string
    s = _settings(tmp_path)
    run_auctions(s, _fetcher(s), years=[2026])
    prices = {r["final_price"] for r in _rows(s) if r["ticker"] not in FIXTURE_RESULTS}
    assert prices == {"26.625"}


@respx.mock
def test_non_json_body_is_not_cached(tmp_path):
    route = respx.get(f"{API}/auction-results/X").mock(
        return_value=httpx.Response(200, content=b"<html>maintenance</html>")
    )
    api = CreditFixingsAPI(Fetcher(cache_dir=tmp_path, delay=0))
    data, status = api.results_by_ticker("X")
    assert data is None and status is not None
    assert not (tmp_path / "cf" / "results_X.json").exists()
    api.results_by_ticker("X")
    assert route.call_count == 2
