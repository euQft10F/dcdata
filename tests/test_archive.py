import json
from urllib.parse import parse_qsl, quote_plus

import httpx
import pytest
import respx
from conftest import FIXTURES

from dcdata import config, schemas
from dcdata.dc import archive
from dcdata.dc.archive import build_archive_form, epoch_to_date, fetch_archive, parse_archive_row
from dcdata.http import Fetcher

DETAIL_ONLY = {"n_history_entries", "n_target_documents", "detail_fetch_status"}


@pytest.fixture(scope="module")
def raw_rows() -> list[list]:
    return json.loads((FIXTURES / "dc_archive_ce.json").read_text(encoding="utf-8"))["aaData"]


@pytest.fixture(scope="module")
def parsed(raw_rows) -> list[dict]:
    return [parse_archive_row(r) for r in raw_rows]


def _by_id(parsed, dc_id):
    return next(r for r in parsed if r["dc_id"] == dc_id)


# ---------------------------------------------------------------- form
def test_build_archive_form_complete():
    form = build_archive_form("credit-event", 500, 250)
    d = dict(form)
    assert len(d) == len(form)  # no duplicate keys
    assert d["sEcho"] == "1"
    assert d["iColumns"] == "8"
    assert d["sColumns"] == ""
    assert d["iDisplayStart"] == "500"
    assert d["iDisplayLength"] == "250"
    assert d["iSortCol_0"] == "0" and d["sSortDir_0"] == "asc" and d["iSortingCols"] == "1"
    assert d["sSearch"] == "" and d["bRegex"] == "false"
    assert d["pageType"] == "credit-default-swaps-archive"
    for i in range(8):
        assert d[f"mDataProp_{i}"] == str(i)
        assert d[f"sSearch_{i}"] == ("credit-event" if i == 2 else "")
        assert d[f"bRegex_{i}"] == "false"
        assert d[f"bSearchable_{i}"] == "true"
        assert d[f"bSortable_{i}"] == "true"
    assert len(form) == 5 + 8 * 5 + 2 + 4


# ---------------------------------------------------------------- epoch
@pytest.mark.parametrize(
    "value, expected",
    [
        (1239840000, "2009-04-16"),
        (" 1782840256 ", "2026-06-30"),
        ("", ""),
        (None, ""),
        ("abc", ""),
    ],
)
def test_epoch_to_date(value, expected):
    assert epoch_to_date(value) == expected


# ---------------------------------------------------------------- row parsing
def test_parse_all_rows(parsed):
    assert len(parsed) == 281
    expected_cols = [c for c in schemas.DC_EVENTS_COLUMNS if c not in DETAIL_ONLY]
    for r in parsed:
        assert sorted(r) == sorted(expected_cols)
        assert all(isinstance(v, str) for v in r.values())
        assert r["dc_id"].startswith("cds/")
        assert r["dc_url"] == f"https://www.cdsdeterminationscommittees.org/{r['dc_id']}/"
        assert r["category"] == "credit-event"
        assert r["date_updated"] and r["submitted_date"]
        assert r["issue_number"]
        assert r["question"] and not r["question"].lower().startswith("question")
        assert r["reference_entity"] == r["reference_entity"].strip()
    assert len({r["dc_id"] for r in parsed}) == 281


def test_dish_row(parsed):
    r = _by_id(parsed, "cds/dish-dbs-corporation")
    assert r["reference_entity"] == "DISH DBS Corporation"
    assert r["issue_number"] == "2026063001"
    assert r["committee_code"] == "americas"
    assert r["committee"] == "Americas"
    assert r["date_updated"] == "2026-10-02"
    assert r["submitted_date"] == "2026-06-30"
    assert r["status"] == "Closed"
    assert r["outcome"] == "Question Decided"
    assert r["question"] == "Has a Bankruptcy Credit Event occurred with respect to DISH DBS Corporation?"
    assert r["transaction_type"] == "Standard North American Corporate/Americas"
    assert r["submitted_by"] == "General Interest Question"
    assert r["coverage_election"] == "2014 Definitions"
    assert r["further_information"].startswith("DISH DBS Corporation and Subsidiaries Initiate")
    assert r["further_information"].endswith("Press release")
    assert "Further Information" not in r["further_information"]


def test_hellenic_row(parsed):
    r = _by_id(parsed, "cds/the-hellenic-republic-2")
    assert r["committee_code"] == "emea-europe"
    assert r["committee"] == "EMEA (Europe)"
    assert r["issue_number"] == "2012022901"
    assert r["transaction_type"] == "Western European Sovereign"


def test_str_epoch_and_missing_epoch(raw_rows):
    row = list(next(r for r in raw_rows if r[3].strip() == "DISH DBS Corporation"))
    as_int = parse_archive_row(row)
    row[4] = str(row[4])
    assert parse_archive_row(row)["submitted_date"] == as_int["submitted_date"] == "2026-06-30"
    row[4] = ""
    assert parse_archive_row(row)["submitted_date"] == ""
    # date_updated falls back to the text date when the epoch part is missing
    row[0] = "October 2, 2026"
    assert parse_archive_row(row)["date_updated"] == "2026-10-02"
    row[0] = "October 2, 2026' '"
    assert parse_archive_row(row)["date_updated"] == "2026-10-02"


def test_relative_and_lcds_more_link():
    html = (
        '<h2 class="credit-title"><em><strong>Question:</strong> Q?</em></h2>'
        '<a class="more-link btn" href="http://www.cdsdeterminationscommittees.org/lcds/cds/foo-2">More</a>'
    )
    r = parse_archive_row(["X' '1", "", "credit-event", " Foo ", 1, "Closed", "None", quote_plus(html)])
    assert r["dc_id"] == "cds/foo-2"
    assert r["dc_url"] == "https://www.cdsdeterminationscommittees.org/cds/foo-2/"
    assert r["question"] == "Q?"
    assert r["reference_entity"] == "Foo"
    r = parse_archive_row(
        ["", "", "credit-event", "", "", "", "", quote_plus('<a class="more-link" href="/cds/bar/">')]
    )
    assert r["dc_url"] == "https://www.cdsdeterminationscommittees.org/cds/bar/"


# ---------------------------------------------------------------- fetch (mocked)
def _mock_endpoint(rows, extra_rows=()):
    data = list(rows) + list(extra_rows)
    total = len(data)
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        form = dict(parse_qsl(request.content.decode(), keep_blank_values=True))
        calls.append(form)
        start, length = int(form["iDisplayStart"]), int(form["iDisplayLength"])
        page = data[start : start + length]
        return httpx.Response(
            200,
            json={
                "sEcho": form["sEcho"],
                "iTotalRecords": total,
                "iTotalDisplayRecords": total,
                "aaData": page,
            },
        )

    return handler, calls


@respx.mock
def test_fetch_archive_paginates_and_caches(tmp_path, raw_rows, monkeypatch):
    monkeypatch.setattr(archive, "PAGE_SIZE", 100)
    handler, calls = _mock_endpoint(raw_rows)
    route = respx.post(config.DC_ARCHIVE_DATA_URL).mock(side_effect=handler)
    f = Fetcher(cache_dir=tmp_path, delay=0)
    rows = fetch_archive(f)
    assert rows == raw_rows
    assert route.call_count == 3
    assert [c["iDisplayStart"] for c in calls] == ["0", "100", "200"]
    assert all(c["sSearch_2"] == "credit-event" and c["iDisplayLength"] == "100" for c in calls)
    for start in (0, 100, 200):
        assert (tmp_path / f"dc/archive_credit-event_{start}.json").exists()
    # second run comes from the cache
    assert fetch_archive(f) == raw_rows
    assert route.call_count == 3
    # refresh forces the network again
    fetch_archive(f, refresh=True)
    assert route.call_count == 6


@respx.mock
def test_fetch_archive_drops_wrong_category(raw_rows, caplog):
    bad = list(raw_rows[0])
    bad[2] = "succession-event"
    handler, _ = _mock_endpoint(raw_rows, [bad])
    respx.post(config.DC_ARCHIVE_DATA_URL).mock(side_effect=handler)
    rows = fetch_archive(Fetcher(delay=0))
    assert len(rows) == 281
    assert any("unexpected category" in m for m in caplog.messages)


@respx.mock
def test_fetch_archive_stops_on_empty_page():
    respx.post(config.DC_ARCHIVE_DATA_URL).mock(
        return_value=httpx.Response(200, json={"iTotalDisplayRecords": 900, "aaData": []})
    )
    assert fetch_archive(Fetcher(delay=0)) == []


@respx.mock
def test_fetch_archive_raises_on_error():
    respx.post(config.DC_ARCHIVE_DATA_URL).mock(return_value=httpx.Response(403))
    with pytest.raises(RuntimeError, match="403"):
        fetch_archive(Fetcher(delay=0))
