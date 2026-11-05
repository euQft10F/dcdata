import hashlib

import httpx
import pytest
import respx
from conftest import make_pdf

from dcdata.dc.documents import convert_documents, download_documents, safe_basename
from dcdata.http import Fetcher

DC = "https://www.cdsdeterminationscommittees.org/documents/2026/07"
PDF_BYTES = b"%PDF-1.5\n%fake pdf body\n"


def link(dc_id, url, is_target=True, seq=0, **kw):
    return {
        "dc_id": dc_id,
        "entry_seq": seq,
        "link_seq": 0,
        "heading": "Ongoing",
        "entry_datetime": "2026-07-10T16:30:00-04:00",
        "link_text": "Americas DC Decision",
        "url": url,
        "url_normalized": url,
        "doc_type": "dc_decision" if is_target else "statement",
        "is_target": is_target,
        "doc_issue_number": "",
        "doc_date": "",
        **kw,
    }


@pytest.fixture
def fetcher():
    f = Fetcher(delay=0, max_retries=0)
    yield f
    f.close()


def run(fetcher, links, tmp_path, **kw):
    return download_documents(fetcher, links, tmp_path / "data" / "documents", base_dir=tmp_path, **kw)


@respx.mock
def test_pdf_served_as_text_html_is_ok(fetcher, tmp_path):
    url = f"{DC}/acme-decision-07-10-26.pdf/"
    respx.get(url).mock(
        return_value=httpx.Response(200, content=PDF_BYTES, headers={"content-type": "text/html"})
    )
    (row,) = run(fetcher, [link("cds/acme", url)], tmp_path)
    assert row["download_status"] == "ok"
    assert row["pdf_path"] == "data/documents/cds_acme/acme-decision-07-10-26.pdf"
    assert row["final_url"] == url
    assert row["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert row["size_bytes"] == len(PDF_BYTES)
    saved = tmp_path / row["pdf_path"]
    assert saved.read_bytes().startswith(b"%PDF-")
    assert not list(saved.parent.glob("*.part"))
    assert row["link_text"] == "Americas DC Decision"  # other columns kept


@respx.mock
def test_html_body_is_not_pdf(fetcher, tmp_path):
    url = f"{DC}/acme-final-list.pdf/"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"<html>login</html>"))
    (row,) = run(fetcher, [link("cds/acme", url)], tmp_path)
    assert row["download_status"] == "not_pdf"
    assert row["pdf_path"] == "" and row["sha256"] == ""
    assert not (tmp_path / "data" / "documents" / "cds_acme" / "acme-final-list.pdf").exists()


@respx.mock
def test_404(fetcher, tmp_path):
    url = "https://www.cdsdeterminationscommittees.org/docs/20090416%20DC%20resolutions.pdf"
    respx.get(url).mock(return_value=httpx.Response(404, content=b"nope"))
    (row,) = run(fetcher, [link("cds/ggp", url)], tmp_path)
    assert row["download_status"] == "http_404"
    assert row["pdf_path"] == ""


@respx.mock
def test_transport_error_does_not_crash(fetcher, tmp_path):
    url = f"{DC}/boom.pdf/"
    respx.get(url).mock(side_effect=httpx.ConnectError("refused"))
    (row,) = run(fetcher, [link("cds/acme", url)], tmp_path)
    assert row["download_status"] == "error:ConnectError"


@respx.mock
def test_duplicate_url_fetched_once(fetcher, tmp_path):
    url = "https://www.cdsdeterminationscommittees.org/documents/2026/04/submission-of-potential-deliverable-obligations.pdf/"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=PDF_BYTES))
    rows = run(fetcher, [link("cds/a", url), link("cds/b", url, seq=3)], tmp_path)
    assert route.call_count == 1
    assert [r["download_status"] for r in rows] == ["ok", "ok"]
    assert rows[0]["pdf_path"] == rows[1]["pdf_path"]
    assert rows[0]["pdf_path"].startswith("data/documents/cds_a/")
    assert [r["dc_id"] for r in rows] == ["cds/a", "cds/b"]
    assert rows[1]["entry_seq"] == 3


@respx.mock
def test_non_target_skipped(fetcher, tmp_path):
    url = f"{DC}/acme-meeting-statement.pdf/"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=PDF_BYTES))
    (row,) = run(fetcher, [link("cds/acme", url, is_target=False)], tmp_path)
    assert route.call_count == 0
    assert row["download_status"] == "skipped_not_target"
    assert all(row[k] == "" for k in ("final_url", "sha256", "size_bytes", "pdf_path"))


@respx.mock
def test_existing_file_reused_without_network(fetcher, tmp_path):
    url = f"{DC}/acme-initial-list.pdf/"
    route = respx.get(url).mock(return_value=httpx.Response(200, content=PDF_BYTES))
    first = run(fetcher, [link("cds/acme", url)], tmp_path)
    assert route.call_count == 1
    second = run(fetcher, [link("cds/acme", url)], tmp_path)
    assert route.call_count == 1  # no new request
    assert second == first  # identical, incl. final_url (remembered in a sidecar)
    third = run(fetcher, [link("cds/acme", url)], tmp_path, refresh=True)
    assert route.call_count == 2 and third == first


def test_existing_file_reused_no_mock_at_all(tmp_path):
    # Pre-existing file and no respx mock: any network access would fail the test.
    url = f"{DC}/acme-preliminary-list.pdf/"
    dest = tmp_path / "data" / "documents" / "cds_acme" / "acme-preliminary-list.pdf"
    dest.parent.mkdir(parents=True)
    dest.write_bytes(PDF_BYTES)
    with respx.mock(assert_all_called=False) as mock:
        f = Fetcher(delay=0, max_retries=0)
        (row,) = run(f, [link("cds/acme", url)], tmp_path)
        assert mock.calls.call_count == 0
    assert row["download_status"] == "ok"
    assert row["sha256"] == hashlib.sha256(PDF_BYTES).hexdigest()
    assert row["size_bytes"] == len(PDF_BYTES)
    assert row["final_url"] == ""


@respx.mock
def test_filename_collision_gets_suffix(fetcher, tmp_path):
    url1 = f"{DC}/final-list.pdf/"
    url2 = "https://www.cdsdeterminationscommittees.org/documents/2026/08/final-list.pdf/"
    respx.get(url1).mock(return_value=httpx.Response(200, content=PDF_BYTES))
    respx.get(url2).mock(return_value=httpx.Response(200, content=PDF_BYTES + b"v2"))
    rows = run(fetcher, [link("cds/acme", url1), link("cds/acme", url2)], tmp_path)
    h = hashlib.sha1(url2.encode()).hexdigest()[:8]
    assert rows[0]["pdf_path"] == "data/documents/cds_acme/final-list.pdf"
    assert rows[1]["pdf_path"] == f"data/documents/cds_acme/final-list__{h}.pdf"
    assert (tmp_path / rows[1]["pdf_path"]).read_bytes().endswith(b"v2")
    # Same file name in a different dc folder is no collision.
    url3 = "https://www.cdsdeterminationscommittees.org/documents/2026/09/final-list.pdf/"
    respx.get(url3).mock(return_value=httpx.Response(200, content=PDF_BYTES))
    (row,) = run(fetcher, [link("cds/other", url3)], tmp_path)
    assert row["pdf_path"] == "data/documents/cds_other/final-list.pdf"


def test_pdf_path_absolute_outside_base(tmp_path):
    with respx.mock:
        url = f"{DC}/x.pdf/"
        respx.get(url).mock(return_value=httpx.Response(200, content=PDF_BYTES))
        f = Fetcher(delay=0, max_retries=0)
        (row,) = download_documents(
            f, [link("cds/x", url)], tmp_path / "docs", base_dir=tmp_path / "elsewhere"
        )
    assert row["pdf_path"] == (tmp_path / "docs" / "cds_x" / "x.pdf").resolve().as_posix()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"{DC}/dish-dbs-corporation-final-list.pdf/", "dish-dbs-corporation-final-list"),
        (
            "https://www.cdsdeterminationscommittees.org/docs/20090416%20200904163%20DC%20resolutions.pdf",
            "20090416_200904163_DC_resolutions",
        ),
        ("https://www.isda.org/dc/docs/EMEA_DC_Statement_01032012.PDF", "EMEA_DC_Statement_01032012"),
        ("https://e.org/a/" + "x" * 200 + ".pdf", "x" * 120),
        ("https://e.org/", "document"),
    ],
)
def test_safe_basename(url, expected):
    assert safe_basename(url) == expected


def test_convert_documents(tmp_path):
    docs = tmp_path / "data" / "documents"
    mds = tmp_path / "data" / "markdown"
    make_pdf(docs / "cds_acme" / "acme-final-list.pdf", "Final List of Deliverable Obligations")
    pdf_path = "data/documents/cds_acme/acme-final-list.pdf"
    rows = [
        {"dc_id": "cds/acme", "download_status": "ok", "pdf_path": pdf_path},
        {"dc_id": "cds/other", "download_status": "ok", "pdf_path": pdf_path},  # dedupe reuse
        {"dc_id": "cds/acme", "download_status": "skipped_not_target", "pdf_path": ""},
        {"dc_id": "cds/acme", "download_status": "http_404", "pdf_path": ""},
    ]
    out = convert_documents(rows, mds, docs, base_dir=tmp_path)
    assert out[0]["md_path"] == "data/markdown/cds_acme/acme-final-list.md"
    assert out[0]["md_status"] == "ok"
    assert out[1]["md_path"] == out[0]["md_path"] and out[1]["md_status"] == "ok"
    assert out[2]["md_path"] == out[2]["md_status"] == ""
    assert out[3]["md_path"] == out[3]["md_status"] == ""
    assert "Final List of Deliverable Obligations" in (tmp_path / out[0]["md_path"]).read_text("utf-8")
    assert "md_path" not in rows[0]  # inputs untouched


@respx.mock
def test_permanent_failures_are_remembered(tmp_path):
    url = "https://e.org/gone.pdf"
    route = respx.get(url).mock(return_value=httpx.Response(404))
    links = [link("cds/x", url)]
    with Fetcher(delay=0, max_retries=0) as f:
        first = download_documents(f, links, tmp_path, base_dir=tmp_path)
        second = download_documents(f, links, tmp_path, base_dir=tmp_path)
        assert route.call_count == 1  # the 404 is not re-requested
        download_documents(f, links, tmp_path, base_dir=tmp_path, refresh=True)
        assert route.call_count == 2  # --refresh retries it
    assert first == second
    assert first[0]["download_status"] == "http_404"


@respx.mock
def test_reuse_reads_sidecar_not_pdf(tmp_path):
    url = "https://e.org/a.pdf"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"%PDF-1.4 body"))
    links = [link("cds/x", url)]
    with Fetcher(delay=0, max_retries=0) as f:
        first = download_documents(f, links, tmp_path, base_dir=tmp_path)
        second = download_documents(f, links, tmp_path, base_dir=tmp_path)
    assert first == second
    assert first[0]["download_status"] == "ok" and first[0]["size_bytes"] == 13
