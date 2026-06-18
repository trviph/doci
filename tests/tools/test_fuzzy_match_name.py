from doci.tools.fuzzy_match_name import fuzzy_match_name


def test_diacritic_insensitive_match():
    r = fuzzy_match_name("CÔNG TY TNHH ABC", "Cong ty TNHH ABC")
    assert r["ok"] is True and r["match"] is True


def test_clear_mismatch():
    assert fuzzy_match_name("ABC Corp", "XYZ Ltd")["match"] is False


def test_custom_threshold():
    assert fuzzy_match_name("ACME", "ACME Co", threshold=50)["match"] is True


def test_empty_input_errors():
    r = fuzzy_match_name("", "ABC")
    assert r["ok"] is False and "error" in r
