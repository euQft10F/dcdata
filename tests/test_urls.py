from dcdata.urls import dc_id_from_url, normalize_dc_url, normalize_url, quote_href, slug_dir


def test_quote_href_spaces_and_existing_escapes():
    assert quote_href("http://x.org/docs/A B.pdf") == "http://x.org/docs/A%20B.pdf"
    assert quote_href("http://x.org/docs/A%20B.pdf") == "http://x.org/docs/A%20B.pdf"


def test_normalize_dc_url_variants():
    canon = "https://www.cdsdeterminationscommittees.org/cds/dish-dbs-corporation/"
    assert normalize_dc_url(canon) == canon
    assert normalize_dc_url("http://www.cdsdeterminationscommittees.org/cds/dish-dbs-corporation") == canon
    assert (
        normalize_dc_url("HTTPS://WWW.cdsdeterminationscommittees.org/cds/dish-dbs-corporation/#x") == canon
    )


def test_normalize_dc_url_repairs_lcds_prefix():
    bad = "https://www.cdsdeterminationscommittees.org/lcds/cds/codere-finance-luxembourg-sa/"
    assert (
        normalize_dc_url(bad)
        == "https://www.cdsdeterminationscommittees.org/cds/codere-finance-luxembourg-sa/"
    )


def test_dc_id_and_slug():
    dc_id = dc_id_from_url("https://www.cdsdeterminationscommittees.org/cds/casino-guichard-perrachon-sa-2/")
    assert dc_id == "cds/casino-guichard-perrachon-sa-2"
    assert slug_dir(dc_id) == "cds_casino-guichard-perrachon-sa-2"


def test_normalize_url_http_to_https_only_for_dc():
    assert normalize_url("http://www.cdsdeterminationscommittees.org/docs/a b.pdf") == (
        "https://www.cdsdeterminationscommittees.org/docs/a%20b.pdf"
    )
    assert normalize_url("http://www.isda.org/dc/docs/X.pdf") == "http://www.isda.org/dc/docs/X.pdf"
