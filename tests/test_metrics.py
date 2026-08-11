import pytest

from app import metrics
from app.metrics import percentile


@pytest.fixture(autouse=True)
def reset_metrics():
    """State của metrics là biến module nên phải reset giữa các test."""
    metrics.TRAFFIC = 0
    metrics.ERRORS.clear()
    yield
    metrics.TRAFFIC = 0
    metrics.ERRORS.clear()


def _ok(n: int = 1) -> None:
    for _ in range(n):
        metrics.record_request(
            latency_ms=100, cost_usd=0.001, tokens_in=10, tokens_out=20, quality_score=0.9
        )


def test_percentile_basic() -> None:
    assert percentile([100, 200, 300, 400], 50) >= 100


def test_error_rate_is_zero_when_no_request_yet() -> None:
    assert metrics.error_rate_pct() == 0.0


def test_error_rate_uses_received_requests_as_denominator() -> None:
    _ok(9)
    metrics.record_error("RuntimeError")
    # 1 loi tren 10 request DA NHAN, khong phai 1/9 request thanh cong.
    assert metrics.error_rate_pct() == 10.0


def test_error_rate_is_100_when_every_request_fails() -> None:
    for _ in range(4):
        metrics.record_error("RuntimeError")
    # Truong hop nay bat duoc loi lay TRAFFIC lam mau so: TRAFFIC=0 se chia cho 0.
    assert metrics.error_rate_pct() == 100.0


def test_snapshot_exposes_error_rate_pct() -> None:
    _ok(3)
    metrics.record_error("ValueError")
    snap = metrics.snapshot()
    assert snap["error_rate_pct"] == 25.0
    assert snap["error_breakdown"] == {"ValueError": 1}
