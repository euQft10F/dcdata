import os

from conftest import make_pdf

from dcdata.pdfmd import pdf_to_markdown


def test_pdf_with_text(tmp_path):
    pdf = tmp_path / "a.pdf"
    make_pdf(pdf, "Final List of Deliverable Obligations for Acme Corp")
    md = tmp_path / "out" / "a.md"
    assert pdf_to_markdown(pdf, md) == "ok"
    content = md.read_bytes()
    assert b"\r\n" not in content
    assert "Final List of Deliverable Obligations for Acme Corp" in content.decode("utf-8")


def test_blank_pdf_is_empty_text(tmp_path):
    pdf = tmp_path / "blank.pdf"
    make_pdf(pdf)
    md = tmp_path / "blank.md"
    assert pdf_to_markdown(pdf, md) == "empty_text"
    assert md.exists()


def test_corrupt_pdf_is_error(tmp_path):
    pdf = tmp_path / "bad.pdf"
    pdf.write_bytes(b"%PDF-1.5\nthis is not really a pdf")
    md = tmp_path / "bad.md"
    status = pdf_to_markdown(pdf, md)
    assert status.startswith("error:")
    assert not md.exists()


def test_skip_when_md_is_newer(tmp_path):
    pdf = tmp_path / "a.pdf"
    make_pdf(pdf, "Some reasonably long text for the test page")
    md = tmp_path / "a.md"
    md.write_text("previous conversion with enough text", encoding="utf-8")
    st = pdf.stat()
    os.utime(md, (st.st_atime + 10, st.st_mtime + 10))
    assert pdf_to_markdown(pdf, md) == "ok"
    assert md.read_text(encoding="utf-8") == "previous conversion with enough text"
    # Status is recomputed from the existing file, so a rerun reports the same status.
    md.write_text("short", encoding="utf-8")
    os.utime(md, (st.st_atime + 10, st.st_mtime + 10))
    assert pdf_to_markdown(pdf, md) == "empty_text"
    # refresh forces reconversion.
    assert pdf_to_markdown(pdf, md, refresh=True) == "ok"
    assert "Some reasonably long text" in md.read_text(encoding="utf-8")
