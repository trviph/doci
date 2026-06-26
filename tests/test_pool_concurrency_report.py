"""The worker boot summary that surfaces the concurrency ↔ pool relationship.

The page fan-out draws `total_concurrency × page_concurrency` connections from a
pool defaulting to 10. At 1×1 today it's masked, but the docs tell operators to
raise the worker concurrency — silently walking into 30s PoolTimeouts. We don't
auto-resize the pool (it also bounds the Supavisor pooler), we warn at boot.
"""

from doci.workflows.runtime import _concurrency_report


def test_warns_when_pool_below_fanout_demand():
    info, warning = _concurrency_report(
        total_concurrency=4, page_concurrency=4, pool_max=10, pool_timeout=30.0
    )
    assert warning is not None
    assert "16" in warning  # 4 × 4 demand
    assert "10" in warning  # configured pool_max
    assert info  # an info line is always produced


def test_quiet_when_pool_covers_demand():
    info, warning = _concurrency_report(
        total_concurrency=1, page_concurrency=4, pool_max=10, pool_timeout=30.0
    )
    assert warning is None
    assert info


def test_quiet_at_exact_capacity():
    _info, warning = _concurrency_report(
        total_concurrency=2, page_concurrency=5, pool_max=10, pool_timeout=30.0
    )
    assert warning is None
