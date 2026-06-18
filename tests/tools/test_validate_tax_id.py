from doci.tools.validate_tax_id import validate_tax_id


def test_valid_vn_lengths():
    assert validate_tax_id("0312345678")["valid"] is True
    assert validate_tax_id("0312345678-001")["valid"] is True  # 13 digits


def test_invalid_length():
    r = validate_tax_id("123")
    assert r["ok"] is True and r["valid"] is False and "expected" in r["reason"]


def test_custom_lengths():
    assert validate_tax_id("12345", valid_lengths=[5])["valid"] is True


def test_empty_errors():
    r = validate_tax_id("")
    assert r["ok"] is False and "error" in r
