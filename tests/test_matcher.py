import json
import re
from collections import Counter
from datetime import UTC, datetime
from urllib.parse import unquote_plus

import pytest
from conftest import FIXTURES

from dcdata.config import Settings
from dcdata.csvio import read_csv, write_csv
from dcdata.match.evaluate import evaluate_grid, format_table
from dcdata.match.matcher import match_auctions
from dcdata.match.pipeline import (
    build_joined,
    final_list_pdf_paths,
    latest_decision_dates,
    run_match,
)
from dcdata.schemas import (
    AUCTIONS_COLUMNS,
    DC_DOCUMENTS_COLUMNS,
    DC_EVENTS_COLUMNS,
    JOINED_COLUMNS,
    MATCHES_COLUMNS,
)
from dcdata.urls import dc_id_from_url, normalize_dc_url, normalize_url

DC = "https://www.cdsdeterminationscommittees.org"

# --------------------------------------------------------------------------------------------
# Helpers: build realistic tables from the captured fixtures (no network, no scraper modules)
# --------------------------------------------------------------------------------------------

_HREF_RE = re.compile(r'<a[^>]*class="more-link[^"]*"[^>]*href="([^"]+)"')
_ISSUE_RE = re.compile(r"Issue Number:</em>\s*<strong>([^<]*)</strong>")


def _epoch_date(v) -> str:
    try:
        return datetime.fromtimestamp(int(str(v).strip()), tz=UTC).date().isoformat()
    except (TypeError, ValueError):
        return ""


def fixture_events() -> list[dict]:
    data = json.loads((FIXTURES / "dc_archive_ce.json").read_text(encoding="utf-8"))
    events = []
    for r in data["aaData"]:
        html = unquote_plus(r[7])
        href = _HREF_RE.search(html).group(1)
        issue = _ISSUE_RE.search(html)
        ev = {c: "" for c in DC_EVENTS_COLUMNS}
        ev.update(
            dc_id=dc_id_from_url(href),
            dc_url=normalize_dc_url(href),
            reference_entity=r[3].strip(),
            committee_code=r[1],
            category=r[2],
            submitted_date=_epoch_date(r[4]),
            status=r[5],
            outcome=r[6],
            issue_number=issue.group(1).strip() if issue else "",
        )
        events.append(ev)
    events.sort(key=lambda e: (e["submitted_date"], e["dc_id"]))
    return events


def fixture_auctions() -> list[dict]:
    rows = []
    for f in sorted(FIXTURES.glob("cf_year_*.json")):
        for a in json.loads(f.read_text(encoding="utf-8")):
            if a.get("auctionType") == "LCDS":
                continue
            row = {c: "" for c in AUCTIONS_COLUMNS}
            row.update(
                auction_id=str(a["auctionID"]),
                auction_year=str(a["auctionYear"]),
                auction_date=a["auctionDate"][:10],
                legal_name=(a.get("legalName") or "").strip(),
                short_name=(a.get("shortName") or "").strip(),
                ticker=a.get("ticker") or "",
                auction_type=a.get("auctionType") or "",
                isda_link=a.get("isdaLink") or "",
            )
            rows.append(row)
    rows.sort(key=lambda r: (r["auction_date"], int(r["auction_id"])))
    return rows


def doc_row(dc_id, url, doc_type="dc_decision", entry_seq=0, link_seq=0, **kw) -> dict:
    row = {c: "" for c in DC_DOCUMENTS_COLUMNS}
    row.update(
        dc_id=dc_id,
        entry_seq=str(entry_seq),
        link_seq=str(link_seq),
        url=url,
        url_normalized=normalize_url(url),
        doc_type=doc_type,
    )
    row.update(kw)
    return row


def fixture_documents() -> list[dict]:
    # Synthetic Procedural-History rows for the two auctions whose isdaLink is a PDF.
    return [
        doc_row(
            "cds/dish-dbs-corporation",
            f"{DC}/documents/2026/07/dish-dbs-decision-07-02-26.pdf/",
        ),
        doc_row(
            "cds/liberty-interactive-llc",
            f"{DC}/documents/2026/04/liberty-interactive-llc-bankruptcy-credit-event-4-21-26.pdf/",
        ),
    ]


def ev(dc_id, entity, submitted, outcome="Question Decided", issue="") -> dict:
    row = {c: "" for c in DC_EVENTS_COLUMNS}
    row.update(
        dc_id=dc_id,
        dc_url=f"{DC}/{dc_id}/",
        reference_entity=entity,
        submitted_date=submitted,
        outcome=outcome,
        issue_number=issue,
    )
    return row


def auc(auction_id, date, legal, link="", short=None) -> dict:
    row = {c: "" for c in AUCTIONS_COLUMNS}
    row.update(
        auction_id=str(auction_id),
        auction_date=date,
        legal_name=legal,
        short_name=short if short is not None else legal,
        isda_link=link,
    )
    return row


# --------------------------------------------------------------------------------------------
# Fixture-derived end-to-end expectations
# --------------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def real():
    return fixture_auctions(), fixture_events(), fixture_documents()


def test_fixture_tables_shape(real):
    auctions, events, _ = real
    assert len(auctions) == 136
    assert len(events) == 281
    assert len({e["dc_id"] for e in events}) == 281


def test_fixture_method_counts(real):
    auctions, events, documents = real
    rows = match_auctions(auctions, events, documents)
    counts = Counter(r["match_method"] for r in rows)
    assert counts == {"exact_link": 133, "normalized_link": 1, "document_link": 2}
    by_id = {r["auction_id"]: r for r in rows}
    assert by_id["9061"]["match_method"] == "normalized_link"
    assert by_id["9061"]["dc_id"] == "cds/codere-finance-luxembourg-sa"
    assert by_id["9187"]["match_method"] == "document_link"
    assert by_id["9187"]["dc_id"] == "cds/dish-dbs-corporation"
    assert by_id["9186"]["match_method"] == "document_link"
    assert by_id["9186"]["dc_id"] == "cds/liberty-interactive-llc"
    for r in rows:
        assert list(r) == MATCHES_COLUMNS
        assert r["match_score"] == "100"
        assert r["needs_review"] == "false"


def test_fixture_without_documents_falls_back_to_fuzzy(real):
    auctions, events, _ = real
    rows = {r["auction_id"]: r for r in match_auctions(auctions, events, [])}
    for aid, dc_id in (("9187", "cds/dish-dbs-corporation"), ("9186", "cds/liberty-interactive-llc")):
        assert rows[aid]["match_method"] == "fuzzy"
        assert rows[aid]["dc_id"] == dc_id


def test_fixture_evaluate(real):
    auctions, events, documents = real
    matches = match_auctions(auctions, events, documents)
    n_truth, grid = evaluate_grid(auctions, events, documents, matches)
    assert n_truth == 133
    cells = {(g["scorer"], g["threshold"]): g for g in grid}
    assert len(cells) == 30
    for g in grid:
        assert g["correct"] + g["wrong"] + g["none"] == 133
    tsr = cells[("token_sort_ratio", 80)]
    assert tsr["correct"] >= 115 and tsr["wrong"] <= 12
    table = format_table(n_truth, grid)
    assert "token_sort_ratio" in table and "WRatio" in table
    print(table)


# --------------------------------------------------------------------------------------------
# Synthetic per-method tests
# --------------------------------------------------------------------------------------------


def test_exact_link_ignores_scheme_case_and_trailing_slash():
    events = [ev("cds/acme-corp", "Acme Corp", "2020-01-01", issue="2020010101")]
    auctions = [
        auc(1, "2020-02-01", "Totally Different", "http://WWW.cdsdeterminationscommittees.org/cds/acme-corp")
    ]
    (row,) = match_auctions(auctions, events, [])
    assert row["match_method"] == "exact_link"
    assert row["dc_id"] == "cds/acme-corp"
    assert row["dc_url"] == f"{DC}/cds/acme-corp/"
    assert row["dc_reference_entity"] == "Acme Corp"
    assert row["dc_issue_number"] == "2020010101"
    assert row["dc_submitted_date"] == "2020-01-01"
    assert row["dc_outcome"] == "Question Decided"
    assert row["match_score"] == "100"
    assert row["needs_review"] == "false"


def test_normalized_link_codere_style():
    events = [ev("cds/codere-finance-luxembourg-sa", "Codere Finance (Luxembourg) S.A.", "2013-09-01")]
    auctions = [
        auc(1, "2013-10-09", "X", f"{DC}/lcds/cds/codere-finance-luxembourg-sa/"),
    ]
    (row,) = match_auctions(auctions, events, [])
    assert row["match_method"] == "normalized_link"
    assert row["dc_id"] == "cds/codere-finance-luxembourg-sa"
    assert row["match_score"] == "100"


def test_link_to_unknown_event_falls_through():
    events = [ev("cds/acme-corp", "Acme Corp", "2020-01-01")]
    auctions = [auc(1, "2020-02-01", "Acme Corporation", f"{DC}/cds/acme-corp-9/")]
    (row,) = match_auctions(auctions, events, [])
    assert row["match_method"] == "fuzzy"
    assert row["dc_id"] == "cds/acme-corp"


def test_document_link_pdf():
    events = [
        ev("cds/dish-dbs-corporation", "DISH DBS Corporation", "2026-06-30"),
        ev("cds/other", "Other Co", "2026-06-30"),
    ]
    pdf = f"{DC}/documents/2026/07/dish-dbs-decision-07-02-26.pdf/"
    docs = [doc_row("cds/dish-dbs-corporation", pdf)]
    # trailing slash and case differences on the path are ignored
    auctions = [
        auc(
            1,
            "2026-08-04",
            "Unrelated Name",
            "http://www.cdsdeterminationscommittees.org/documents/2026/07/DISH-dbs-decision-07-02-26.pdf",
        )
    ]
    (row,) = match_auctions(auctions, events, docs)
    assert row["match_method"] == "document_link"
    assert row["dc_id"] == "cds/dish-dbs-corporation"
    assert row["match_score"] == "100"
    assert row["n_candidates"] == "1"


def test_document_link_several_dc_ids_uses_fuzzy_ranking():
    pdf = f"{DC}/documents/2020/01/shared-list.pdf"
    events = [
        ev("cds/alpha-inc", "Alpha Inc.", "2020-01-01"),
        ev("cds/beta-plc", "Beta PLC", "2020-01-01"),
        ev("cds/beta-plc-2", "Beta PLC", "2020-01-01"),  # not referencing the doc
    ]
    docs = [doc_row("cds/alpha-inc", pdf), doc_row("cds/beta-plc", pdf)]
    (row,) = match_auctions([auc(1, "2020-02-01", "Beta", pdf)], events, docs)
    assert row["match_method"] == "document_link"
    assert row["dc_id"] == "cds/beta-plc"
    assert row["n_candidates"] == "2"
    assert row["runner_up_dc_id"] == "cds/alpha-inc"


def test_document_link_ignores_documents_of_unknown_events():
    pdf = f"{DC}/documents/2020/01/x.pdf/"
    docs = [doc_row("cds/ghost", pdf)]
    (row,) = match_auctions([auc(1, "2020-02-01", "Nobody", pdf)], [ev("cds/a", "Alpha", "2020-01-01")], docs)
    assert row["match_method"] == "unmatched"


def test_fuzzy_date_window_picks_right_event():
    events = [
        ev("cds/casino-guichard-perrachon-sa", "Casino Guichard-Perrachon S.A.", "2019-01-10"),
        ev("cds/casino-guichard-perrachon-sa-2", "Casino Guichard-Perrachon S.A.", "2024-03-01"),
    ]
    auctions = [auc(1, "2024-04-10", "Casino Guichard Perrachon SA")]
    (row,) = match_auctions(auctions, events, [])
    assert row["match_method"] == "fuzzy"
    assert row["dc_id"] == "cds/casino-guichard-perrachon-sa-2"
    assert row["n_candidates"] == "1"
    assert row["needs_review"] == "false"
    assert row["match_score"] == "100"


def test_fuzzy_window_bounds_inclusive():
    events = [
        ev("cds/a", "Acme", "2020-01-08"),  # gap -7 (allowed)
    ]
    (row,) = match_auctions([auc(1, "2020-01-01", "Acme")], events, [])
    assert row["dc_id"] == "cds/a"
    (row,) = match_auctions([auc(1, "2020-01-01", "Acme")], events, [], date_window=(-6, 365))
    assert row["match_method"] == "unmatched"


def test_fuzzy_excludes_events_without_submitted_date():
    (row,) = match_auctions([auc(1, "2020-01-01", "Acme")], [ev("cds/a", "Acme", "")], [])
    assert row["match_method"] == "unmatched"
    assert row["match_score"] == ""
    assert row["dc_id"] == ""
    assert row["n_candidates"] == "0"


def test_fuzzy_prefers_decided_over_rejected():
    events = [
        ev("cds/acme", "Acme", "2020-01-20", outcome="Rejected"),  # closer in time
        ev("cds/acme-2", "Acme", "2020-01-01", outcome="Question Decided"),
    ]
    (row,) = match_auctions([auc(1, "2020-01-25", "Acme")], events, [])
    assert row["dc_id"] == "cds/acme-2"
    assert row["n_candidates"] == "2"
    assert row["runner_up_dc_id"] == "cds/acme"
    assert row["runner_up_score"] == "100"
    assert row["needs_review"] == "true"


def test_fuzzy_closer_gap_wins_then_dc_id_tiebreak():
    events = [
        ev("cds/acme", "Acme", "2020-01-01"),
        ev("cds/acme-2", "Acme", "2020-01-15"),
    ]
    (row,) = match_auctions([auc(1, "2020-01-20", "Acme")], events, [])
    assert row["dc_id"] == "cds/acme-2"
    # identical everything -> highest dc_id wins (descending tuple), independent of input order
    events = [ev("cds/acme-b", "Acme", "2020-01-01"), ev("cds/acme-a", "Acme", "2020-01-01")]
    for evs in (events, events[::-1]):
        (row,) = match_auctions([auc(1, "2020-01-20", "Acme")], evs, [])
        assert row["dc_id"] == "cds/acme-b"
        assert row["runner_up_dc_id"] == "cds/acme-a"
        assert row["needs_review"] == "true"


def test_fuzzy_short_name_used_and_threshold():
    events = [ev("cds/x", "Lehman Brothers Holdings Inc.", "2008-09-15")]
    a = auc(1, "2008-10-10", "LBHI Something Unrelated", short="Lehman Brothers")
    (row,) = match_auctions([a], events, [])
    assert row["match_method"] == "fuzzy"
    assert row["dc_id"] == "cds/x"
    (row,) = match_auctions([auc(1, "2008-10-10", "Totally Other Name")], events, [])
    assert row["match_method"] == "unmatched"


def test_unknown_scorer_raises():
    with pytest.raises(ValueError):
        match_auctions([], [], [], scorer="nope")


def test_output_sort_order_and_columns():
    events = [ev("cds/a", "Alpha", "2020-01-01")]
    auctions = [
        auc(10, "2020-03-01", "Alpha"),
        auc(9, "2020-03-01", "Alpha"),
        auc(100, "2020-02-01", "Alpha"),
        auc(2, "2020-03-01", "Alpha"),
    ]
    rows = match_auctions(auctions, events, [])
    assert [r["auction_id"] for r in rows] == ["100", "2", "9", "10"]
    assert all(list(r) == MATCHES_COLUMNS for r in rows)
    assert match_auctions(auctions[::-1], events[::-1], []) == rows


# --------------------------------------------------------------------------------------------
# Joined table / pipeline
# --------------------------------------------------------------------------------------------


def test_latest_decision_and_final_list():
    docs = [
        doc_row("cds/a", "u1", "dc_decision", doc_date="2020-01-05"),
        doc_row("cds/a", "u2", "dc_decision", entry_datetime="2020-02-01T10:00:00-05:00"),
        doc_row(
            "cds/a",
            "u3",
            "final_list",
            1,
            0,
            entry_datetime="2020-02-01T10:00:00-05:00",
            pdf_path="p/old.pdf",
        ),
        doc_row(
            "cds/a",
            "u4",
            "final_list",
            2,
            0,
            entry_datetime="2020-02-02T10:00:00-05:00",
            pdf_path="p/new.pdf",
        ),
        doc_row("cds/a", "u5", "final_list", 3, 0, entry_datetime="2020-03-01T10:00:00-05:00", pdf_path=""),
        doc_row(
            "cds/a",
            "u6",
            "initial_list",
            4,
            0,
            entry_datetime="2021-01-01T10:00:00-05:00",
            pdf_path="p/i.pdf",
        ),
        doc_row(
            "cds/b", "u7", "final_list", 1, 0, entry_datetime="2020-02-01T10:00:00-05:00", pdf_path="b/x.pdf"
        ),
        doc_row(
            "cds/b", "u8", "final_list", 1, 1, entry_datetime="2020-02-01T10:00:00-05:00", pdf_path="b/y.pdf"
        ),
        doc_row("cds/b", "u9", "meeting_statement", doc_date="2030-01-01"),
    ]
    assert latest_decision_dates(docs) == {"cds/a": "2020-02-01"}
    assert final_list_pdf_paths(docs) == {"cds/a": "p/new.pdf", "cds/b": "b/y.pdf"}


def test_joined_includes_unmatched_events_once():
    events = [
        ev("cds/b", "Beta", "2020-01-01"),
        ev("cds/a", "Alpha", "2020-01-01"),
        ev("cds/z", "Zulu Never Auctioned", "2019-01-01"),
    ]
    auctions = [
        auc(5, "2020-02-01", "Alpha", f"{DC}/cds/a/"),
        auc(4, "2020-02-01", "Alpha", f"{DC}/cds/a/"),
        auc(3, "2020-01-15", "Alpha", f"{DC}/cds/a/"),
    ]
    matches = match_auctions(auctions, events, [])
    joined = build_joined(events, matches, [doc_row("cds/a", "u", "dc_decision", doc_date="2020-01-10")])
    keys = [(r["dc_id"], r["auction_id"]) for r in joined]
    assert keys == [("cds/z", ""), ("cds/a", "3"), ("cds/a", "4"), ("cds/a", "5"), ("cds/b", "")]
    assert joined[1]["match_method"] == "exact_link"
    assert joined[1]["latest_decision_date"] == "2020-01-10"
    assert joined[0]["match_method"] == "" and joined[0]["latest_decision_date"] == ""


def test_run_match_writes_csvs(tmp_path, real, capsys):
    auctions, events, documents = real
    settings = Settings(data_dir=tmp_path)
    out = settings.output_dir
    write_csv(auctions, out / "auctions.csv", AUCTIONS_COLUMNS)
    write_csv(events, out / "dc_credit_events.csv", DC_EVENTS_COLUMNS)
    write_csv(documents, out / "dc_documents.csv", DC_DOCUMENTS_COLUMNS)

    summary = run_match(settings, evaluate=True)
    assert summary["n_auctions"] == 136
    assert summary["methods"] == {
        "exact_link": 133,
        "normalized_link": 1,
        "document_link": 2,
        "fuzzy": 0,
        "unmatched": 0,
    }
    assert summary["n_needs_review"] == 0
    assert summary["n_events"] == 281
    assert "token_sort_ratio" in summary["evaluate"]
    assert "token_sort_ratio" in capsys.readouterr().out

    matches_bytes = (out / "matches.csv").read_bytes()
    joined = read_csv(out / "credit_events_with_auctions.csv")
    assert list(joined[0]) == JOINED_COLUMNS
    with_auction = {r["dc_id"] for r in joined if r["auction_id"]}
    assert summary["n_events_with_auction"] == len(with_auction)
    n_without = sum(1 for r in joined if not r["auction_id"])
    assert len(joined) == 136 + n_without
    assert n_without == 281 - len(with_auction)

    # deterministic: a second run produces identical bytes
    run_match(settings)
    assert (out / "matches.csv").read_bytes() == matches_bytes


def test_run_match_missing_input(tmp_path):
    with pytest.raises(FileNotFoundError, match="dcdata auctions"):
        run_match(Settings(data_dir=tmp_path))
