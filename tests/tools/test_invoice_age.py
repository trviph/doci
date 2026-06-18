from doci.tools.invoice_age import invoice_age


def test_over_max_age():
    r = invoice_age("01/01/2020", ref_date="01/01/2021")
    assert r["over_max"] is True and r["future_dated"] is False


def test_future_dated():
    r = invoice_age("01/01/2030", ref_date="01/01/2026")
    assert r["future_dated"] is True


def test_within_age_custom_max():
    r = invoice_age("01/01/2026", ref_date="01/03/2026", max_days=365)
    assert r["over_max"] is False


def test_unparseable_errors():
    r = invoice_age("nope")
    assert r["ok"] is False and "error" in r
