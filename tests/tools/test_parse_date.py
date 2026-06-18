from doci.tools.parse_date import parse_date, to_date


def test_to_date_formats():
    assert to_date("ngày 12 tháng 01 năm 2026") == "2026-01-12"
    assert to_date("12 tháng 1 năm 2026") == "2026-01-12"
    assert to_date("12/01/2026") == "2026-01-12"
    assert to_date("12-01-2026") == "2026-01-12"
    assert to_date("2026-01-12") == "2026-01-12"


def test_to_date_unparseable():
    assert to_date("rubbish") is None
    assert to_date("") is None


def test_parse_date_tool_response():
    assert parse_date("12/01/2026") == {"ok": True, "date": "2026-01-12"}
    bad = parse_date("nope")
    assert bad["ok"] is False and "error" in bad
