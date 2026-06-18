from doci.tools.compare_amount import compare_amount


def test_within_absolute_tolerance():
    r = compare_amount("1.000.000", "1.000.500")  # 500 < min(1%,100k)
    assert r["ok"] is True and r["match"] is True


def test_beyond_tolerance():
    r = compare_amount("1.000.000", "1.200.000")  # 200k > min(1%,100k)
    assert r["match"] is False


def test_custom_tolerance_min_semantics():
    # allowed = smaller of (tol_pct% of larger, tol_abs)
    assert compare_amount("1000", "1010", tol_pct=2.0, tol_abs=1000)["match"] is True   # min(20.2,1000)
    assert compare_amount("1000", "1010", tol_pct=5.0, tol_abs=5)["match"] is False     # min(50,5)=5 < 10


def test_unparseable_is_not_a_mismatch():
    r = compare_amount("x", "1000")
    assert r["ok"] is False and "error" in r