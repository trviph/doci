from doci.tools.check_date_order import check_date_order


def test_in_order():
    r = check_date_order([
        {"label": "PR", "date": "01/01/2026"},
        {"label": "PO", "date": "05/01/2026"},
        {"label": "Invoice", "date": "10/01/2026"},
    ])
    assert r["ordered"] is True and r["violations"] == []


def test_out_of_order():
    r = check_date_order([
        {"label": "PR", "date": "01/01/2026"},
        {"label": "PO", "date": "05/01/2026"},
        {"label": "Invoice", "date": "03/01/2026"},
    ])
    assert r["ordered"] is False and len(r["violations"]) == 1


def test_unparsed_reported_not_fatal():
    r = check_date_order([
        {"label": "PR", "date": "01/01/2026"},
        {"label": "PO", "date": "???"},
    ])
    assert r["ok"] is True and "PO" in r["unparsed"]