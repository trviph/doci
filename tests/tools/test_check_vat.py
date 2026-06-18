from doci.tools.check_vat import check_vat


def test_correct_vat_and_valid_rate():
    r = check_vat("10.000.000", "10", "1.000.000")
    assert r["match"] is True and r["rate_valid"] is True


def test_rate_not_in_default_set():
    r = check_vat("10.000.000", "7", "700.000")
    assert r["rate_valid"] is False  # 7% not in VN default {0,5,8,10}


def test_custom_allowed_rates():
    r = check_vat("10.000.000", "7", "700.000", allowed_rates=[7])
    assert r["rate_valid"] is True and r["match"] is True


def test_unparseable_errors():
    r = check_vat("x", "10", "y")
    assert r["ok"] is False and "error" in r
