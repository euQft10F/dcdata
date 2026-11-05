import pytest

from dcdata.match.normalize import normalize_name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Casino Guichard-Perrachon S.A.", "casino guichard perrachon"),
        ("The Hellenic Republic", "hellenic republic"),
        ("Lehman Brothers Holdings Inc.", "lehman brothers"),
        ("CODERE FINANCE (LUXEMBOURG) S.A.", "codere finance"),
        ("CODERE Fin LUXEMBOURG SA", "codere fin luxembourg"),
        ("DISH DBS Corporation", "dish dbs"),
        ("Ambac Financial Group, Inc.", "ambac financial"),
        ("Thomson Reuters & Co. Ltd", "thomson reuters and"),
        ("Société Générale S.A.", "societe generale"),
        ("Grupo Elektra, S.A.B. de C.V.", "grupo elektra"),
        ("Cemex SAB de CV", "cemex"),
        ("Nortel Networks Public Limited Company", "nortel networks"),
        ("Banco Popular Español, Sociedad Anónima", "banco popular espanol"),
        ("Astaldi Società per Azioni", "astaldi"),
        ("Abengoa Abenewco 2, S.A.U.", "abengoa abenewco 2 u"),
        ("Washington Mutual, Inc. (formerly WaMu)", "washington mutual"),
        ("Windstream Services LLC formerly known as Windstream Corp", "windstream services"),
        ("Frontier Communications Parent f/k/a Frontier Corp", "frontier communications parent"),
        ("  Multiple   Spaces  GmbH ", "multiple spaces"),
        ("Neiman Marcus Group LTD LLC", "neiman marcus"),
        ("", ""),
    ],
)
def test_normalize_name(raw, expected):
    assert normalize_name(raw) == expected


def test_suffixes_are_whole_tokens_not_substrings():
    # "sa" / "co" / "ag" / "ab" must not be removed from inside words
    assert normalize_name("Sabre Holdings Corp") == "sabre"
    assert normalize_name("Codere SA") == "codere"
    assert normalize_name("Agfa Abbott Coop") == "agfa abbott coop"
    # "s a" only as an adjacent token pair
    assert normalize_name("Oi S A") == "oi"
    assert normalize_name("S Group A") == "s a"


def test_all_stop_tokens_falls_back_to_tokens():
    assert normalize_name("The Group Company") == "the group company"


def test_unicode_folding():
    assert normalize_name("Ålandsbanken Abp") == "alandsbanken abp"
