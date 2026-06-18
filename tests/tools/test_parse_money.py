from doci.tools.parse_money import parse_money, to_money


def test_to_money_thousands_and_decimals():
    assert to_money("27,540,000 VNĐ") == 27540000.0
    assert to_money("1.200.000đ") == 1200000.0
    assert to_money("1.200,50") == 1200.50
    assert to_money("1,200.50") == 1200.50
    assert to_money("10.5") == 10.5
    assert to_money(5000) == 5000.0


def test_to_money_unparseable():
    assert to_money("n/a") is None
    assert to_money("") is None


def test_parse_money_tool_response():
    assert parse_money("27,540,000 VNĐ") == {"ok": True, "value": 27540000.0}
    bad = parse_money("rubbish")
    assert bad["ok"] is False and "error" in bad
