from dcdata.urls import (
    dc_id_from_url,
    dc_path_repaired,
    dc_url_key,
    normalize_dc_url,
    quote_href,
    slug_dir,
)


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


def test_dc_id_and_slug():
    dc_id = dc_id_from_url("https://www.cdsdeterminationscommittees.org/cds/casino-guichard-perrachon-sa-2/")
    assert dc_id == "cds/casino-guichard-perrachon-sa-2"
    assert slug_dir(dc_id) == "cds_casino-guichard-perrachon-sa-2"


def test_dc_url_key_and_repair_flag():
    canon = "https://www.cdsdeterminationscommittees.org/cds/foo/"
    assert dc_url_key("http://cdsdeterminationscommittees.org/CDS/Foo") == dc_url_key(canon)
    assert not dc_path_repaired(canon)
    assert dc_path_repaired("https://www.cdsdeterminationscommittees.org/lcds/cds/foo/")
    assert dc_path_repaired("https://www.cdsdeterminationscommittees.org/LCDS/CDS/foo/")
