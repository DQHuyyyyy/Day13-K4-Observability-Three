from __future__ import annotations

from collections import Counter
from statistics import mean

REQUEST_LATENCIES: list[int] = []
REQUEST_COSTS: list[float] = []
REQUEST_TOKENS_IN: list[int] = []
REQUEST_TOKENS_OUT: list[int] = []
ERRORS: Counter[str] = Counter()
TRAFFIC: int = 0
QUALITY_SCORES: list[float] = []


def record_request(latency_ms: int, cost_usd: float, tokens_in: int, tokens_out: int, quality_score: float) -> None:
    global TRAFFIC
    TRAFFIC += 1
    REQUEST_LATENCIES.append(latency_ms)
    REQUEST_COSTS.append(cost_usd)
    REQUEST_TOKENS_IN.append(tokens_in)
    REQUEST_TOKENS_OUT.append(tokens_out)
    QUALITY_SCORES.append(quality_score)



def record_error(error_type: str) -> None:
    ERRORS[error_type] += 1



def percentile(values: list[int], p: int) -> float:
    if not values:
        return 0.0
    items = sorted(values)
    idx = max(0, min(len(items) - 1, round((p / 100) * len(items) + 0.5) - 1))
    return float(items[idx])



def error_rate_pct() -> float:
    """Tỉ lệ lỗi tính động tại thời điểm gọi, đơn vị phần trăm.

    Mẫu số là **tổng request đã nhận**, không phải số request thành công.
    `TRAFFIC` chỉ tăng trong `record_request()`, mà hàm đó nằm ở cuối
    `LabAgent.run` — request lỗi ném exception trước khi tới đó nên không bao
    giờ được đếm. Lấy `TRAFFIC` làm mẫu số sẽ báo 0% đúng lúc mọi request đều
    hỏng, và chia cho 0 khi chưa có request nào thành công.

    Định nghĩa này khớp với panel `errors` trong `config/dashboard.yaml`:
    `count(request_failed) / count(request_received) * 100`.
    """
    failed = sum(ERRORS.values())
    received = TRAFFIC + failed
    if received == 0:
        return 0.0
    return round(failed / received * 100, 2)


def snapshot() -> dict:
    return {
        "traffic": TRAFFIC,
        "latency_p50": percentile(REQUEST_LATENCIES, 50),
        "latency_p95": percentile(REQUEST_LATENCIES, 95),
        "latency_p99": percentile(REQUEST_LATENCIES, 99),
        "avg_cost_usd": round(mean(REQUEST_COSTS), 4) if REQUEST_COSTS else 0.0,
        "total_cost_usd": round(sum(REQUEST_COSTS), 4),
        "tokens_in_total": sum(REQUEST_TOKENS_IN),
        "tokens_out_total": sum(REQUEST_TOKENS_OUT),
        "error_breakdown": dict(ERRORS),
        "error_rate_pct": error_rate_pct(),
        "quality_avg": round(mean(QUALITY_SCORES), 4) if QUALITY_SCORES else 0.0,
    }
