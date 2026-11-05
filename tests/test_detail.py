from pathlib import Path

import pytest

from dcdata import schemas
from dcdata.dc.detail import parse_procedural_history

FIXTURES = Path(__file__).parent / "fixtures"
LINK_KEYS = [
    "dc_id",
    "entry_seq",
    "link_seq",
    "heading",
    "entry_datetime",
    "link_text",
    "url",
    "url_normalized",
]


def _parse(slug):
    html = (FIXTURES / f"dc_detail_{slug}.html").read_text(encoding="utf-8")
    result = parse_procedural_history(html, f"cds/{slug}")
    assert result is not None
    return result


@pytest.mark.parametrize(
    "slug, n_entries, n_links",
    [
        ("dish-dbs-corporation", 19, 24),
        ("general-growth-properties-inc", 3, 1),
        ("the-hellenic-republic-2", 2, 2),
        ("credit-suisse-group-ag", 4, 1),
    ],
)
def test_shapes_and_invariants(slug, n_entries, n_links):
    entries, links = _parse(slug)
    assert len(entries) == n_entries
    assert len(links) == n_links
    assert [e["entry_seq"] for e in entries] == list(range(n_entries))
    for e in entries:
        assert list(e) == schemas.DC_HISTORY_COLUMNS
        assert e["dc_id"] == f"cds/{slug}"
        assert e["heading"] and e["entry_datetime"]
        assert e["n_links"] == sum(1 for lk in links if lk["entry_seq"] == e["entry_seq"])
        assert "\xa0" not in e["entry_text"]
    for lk in links:
        assert list(lk) == LINK_KEYS
        entry = entries[lk["entry_seq"]]
        assert lk["heading"] == entry["heading"]
        assert lk["entry_datetime"] == entry["entry_datetime"]
    # link_seq is 0-based and contiguous within each entry
    for e in entries:
        seqs = [lk["link_seq"] for lk in links if lk["entry_seq"] == e["entry_seq"]]
        assert seqs == list(range(e["n_links"]))
    # datetimes are non-decreasing from oldest to newest
    dts = [e["entry_datetime"] for e in entries]
    assert dts == sorted(dts)


def test_dish():
    entries, links = _parse("dish-dbs-corporation")
    assert entries[0]["heading"] == "Pending DC Consent"
    assert entries[0]["entry_datetime"] == "2026-06-30T17:25:00-04:00"
    assert entries[0]["entry_text"] == "" and entries[0]["n_links"] == 0
    assert entries[1]["heading"] == "Request Accepted by DC"
    assert entries[-1]["heading"] == "Closed"
    assert entries[-1]["entry_datetime"] == "2026-10-02T18:35:00-04:00"

    final_lists = [e for e in entries if e["heading"] == "Final List Published"]
    assert len(final_lists) == 3
    assert [e["n_links"] for e in final_lists] == [1, 3, 3]

    # DC decisions sit under "Ongoing" headings
    ongoing_texts = [lk["link_text"] for lk in links if lk["heading"] == "Ongoing"]
    assert "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 08/10/26" in ongoing_texts

    e = entries[16]
    assert e["heading"] == "Final List Published"
    assert e["entry_datetime"] == "2026-08-04T08:30:00-04:00"
    lines = e["entry_text"].split("\n")
    assert lines[0] == "Americas DC Meeting Statement - August 4, 2026"
    assert lines[1].startswith(
        "The Americas DC met today to discuss the DISH DBS Corporation Auction Final List."
    )
    assert lines[-1] == "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 08/04/26"
    assert len(lines) == 5  # the trailing "<p>&nbsp;</p>" is dropped
    e_links = [lk for lk in links if lk["entry_seq"] == 16]
    assert [lk["link_text"] for lk in e_links] == [
        "Americas DC - DISH DBS Corporation - Final List of Deliverable Obligations",
        "Redline of updated Final List of Deliverable Obligations against previously published Final List",
        "Americas DC Decision - Issue Number 2026063001 (DISH DBS Corporation) - 08/04/26",
    ]
    assert e_links[0]["url"] == (
        "https://www.cdsdeterminationscommittees.org/documents/2026/08/dish-dbs-corporation-final-list-updated.pdf/"
    )
    assert e_links[0]["url_normalized"] == e_links[0]["url"]


def test_general_growth_legacy_link():
    entries, links = _parse("general-growth-properties-inc")
    assert [e["heading"] for e in entries] == ["Request Accepted by DC", "Closed", "Closed"]
    assert entries[0]["entry_text"] == "Yes - a bankruptcy credit event has occured"
    (lk,) = links
    assert lk["link_text"] == "View Attachment"
    assert lk["entry_seq"] == 2
    assert (
        lk["url"] == "http://www.cdsdeterminationscommittees.org/docs/20090416 200904163 DC resolutions.pdf"
    )
    assert lk["url_normalized"] == (
        "https://www.cdsdeterminationscommittees.org/docs/20090416%20200904163%20DC%20resolutions.pdf"
    )


def test_hellenic_isda_links():
    entries, links = _parse("the-hellenic-republic-2")
    assert [e["heading"] for e in entries] == ["Pending DC Consent", "Closed"]
    assert [lk["link_text"] for lk in links] == [
        "EMEA Determinations Committee Decision 01032012",
        "EMEA DC Statement 01032012",
    ]
    assert [lk["link_seq"] for lk in links] == [0, 1]
    assert all(lk["url"].startswith("http://www.isda.org/dc/docs/") for lk in links)
    # isda.org is not the DC host, so the scheme is left alone
    assert links[0]["url_normalized"] == (
        "http://www.isda.org/dc/docs/EMEA_Determinations_Committee_Decision_01032012Q2.pdf"
    )


def test_credit_suisse_short_history():
    entries, links = _parse("credit-suisse-group-ag")
    assert [e["heading"] for e in entries] == [
        "Pending DC Consent",
        "Request Accepted by DC",
        "Ongoing",
        "Closed",
    ]
    assert links[0]["link_text"] == "DC Decision"
    assert links[0]["heading"] == "Closed"
    text = entries[3]["entry_text"]
    assert text.startswith("DC Decision\nEMEA DC Meeting Statement - 17 May 2023\n")
    assert text.endswith("as it abstained under the DC Rules.")


def test_no_history_returns_none():
    html = "<html><body><ul class='other'><li><h4>Closed</h4></li></ul></body></html>"
    assert parse_procedural_history(html, "cds/x") is None
    assert parse_procedural_history("", "cds/x") is None


def test_nested_lists_and_skipped_links():
    html = """
    <ul class="ProceduralHistory">
      <li>
        <h4>Ongoing</h4>
        <p><p>First&nbsp;para <a href="mailto:a@b.c">mail</a> <a href="#top">top</a></p>
        <p><a href=" /documents/x y.pdf/ ">Doc   one</a></p></p>
        <ul><li>nested item <a href="https://e.org/n.pdf">Nested</a></li></ul>
        loose text
        <time datetime="2020-01-02T00:00:00-05:00">1/2/2020</time>
      </li>
      <li>
        <h4>Pending DC Consent</h4>
        <p></p>
        <time datetime="2020-01-01T00:00:00-05:00">1/1/2020</time>
      </li>
    </ul>"""
    entries, links = parse_procedural_history(html, "cds/x")
    assert [e["heading"] for e in entries] == ["Pending DC Consent", "Ongoing"]
    e = entries[1]
    assert e["entry_text"] == "First para mail top\nDoc one\nnested item Nested\nloose text"
    assert e["n_links"] == 2
    assert [(lk["link_seq"], lk["link_text"], lk["url"]) for lk in links] == [
        (0, "Doc one", "/documents/x y.pdf/"),
        (1, "Nested", "https://e.org/n.pdf"),
    ]
    assert links[0]["url_normalized"] == "/documents/x%20y.pdf/"
