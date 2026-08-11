"""Dựng dashboard 6 panel từ `data/logs.jsonl` theo contract `config/dashboard.yaml`.

Tên panel, đơn vị, threshold và cửa sổ thời gian đều đọc thẳng từ contract chứ
không hard-code, nên ảnh dashboard nộp kèm chứng minh được là khớp contract.
`validate_dashboard.py` chỉ kiểm tra cấu trúc YAML; script này mới là phần dựng.

    python scripts/build_dashboard.py
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.cli import configure_utf8_stdio
from app.metrics import percentile

DEFAULT_LOGS = REPO_ROOT / "data" / "logs.jsonl"
DEFAULT_CONFIG = REPO_ROOT / "config" / "dashboard.yaml"
DEFAULT_OUT = REPO_ROOT / "submission" / "evidence" / "dashboard.html"

# Palette lấy từ reference đã validate (ordinal blue cho quantile, categorical
# blue/orange cho token). Mọi cặp đã chạy qua validator ở cả light lẫn dark.
SERIES = {
    "q50": ("--seq-1", "P50"),
    "q95": ("--seq-2", "P95"),
    "q99": ("--seq-3", "P99"),
}


# --------------------------------------------------------------------------- data


def _parse_ts(raw: str) -> datetime:
    return datetime.fromisoformat(raw.replace("Z", "+00:00"))


def load_records(log_path: Path, window_minutes: int) -> tuple[list[dict], datetime, datetime]:
    if not log_path.exists():
        raise SystemExit(f"Không tìm thấy {log_path}. Chạy API và scripts/load_test.py trước.")

    records = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "ts" not in rec:
            continue
        rec["_ts"] = _parse_ts(rec["ts"])
        records.append(rec)

    if not records:
        raise SystemExit(f"{log_path} chưa có log hợp lệ nào.")

    # Cửa sổ neo vào bản ghi mới nhất, không neo vào "bây giờ": file log là ảnh
    # chụp tại thời điểm chạy load test, đọc theo giờ hiện tại sẽ ra panel rỗng.
    end = max(r["_ts"] for r in records)
    start = end - timedelta(minutes=window_minutes)
    inside = [r for r in records if start <= r["_ts"] <= end]
    return inside, start, end


def minute_buckets(start: datetime, end: datetime) -> list[datetime]:
    first = start.replace(second=0, microsecond=0)
    last = end.replace(second=0, microsecond=0)
    out, cur = [], first
    while cur <= last:
        out.append(cur)
        cur += timedelta(minutes=1)
    return out


def _key(ts: datetime) -> datetime:
    return ts.replace(second=0, microsecond=0)


def compute(records: list[dict], buckets: list[datetime]) -> dict:
    received = [r for r in records if r.get("event") == "request_received"]
    failed = [r for r in records if r.get("event") == "request_failed"]
    sent = [r for r in records if r.get("event") == "response_sent"]

    lat_by_min: dict[datetime, list[int]] = defaultdict(list)
    for r in sent:
        lat_by_min[_key(r["_ts"])].append(int(r["latency_ms"]))

    traffic = Counter(_key(r["_ts"]) for r in received)
    fail_by_min = Counter(_key(r["_ts"]) for r in failed)

    cost_by_min: dict[datetime, float] = defaultdict(float)
    tin_by_min: dict[datetime, int] = defaultdict(int)
    tout_by_min: dict[datetime, int] = defaultdict(int)
    qual_by_min: dict[datetime, list[float]] = defaultdict(list)
    for r in sent:
        k = _key(r["_ts"])
        cost_by_min[k] += float(r.get("cost_usd") or 0.0)
        tin_by_min[k] += int(r.get("tokens_in") or 0)
        tout_by_min[k] += int(r.get("tokens_out") or 0)
        if r.get("quality_score") is not None:
            qual_by_min[k].append(float(r["quality_score"]))

    all_lat = [int(r["latency_ms"]) for r in sent]
    quality_all = [float(r["quality_score"]) for r in sent if r.get("quality_score") is not None]
    active = [b for b in buckets if traffic.get(b)]

    return {
        "buckets": buckets,
        "latency": {
            "q50": [percentile(lat_by_min.get(b, []), 50) if lat_by_min.get(b) else None for b in buckets],
            "q95": [percentile(lat_by_min.get(b, []), 95) if lat_by_min.get(b) else None for b in buckets],
            "q99": [percentile(lat_by_min.get(b, []), 99) if lat_by_min.get(b) else None for b in buckets],
            "p50": percentile(all_lat, 50),
            "p95": percentile(all_lat, 95),
            "p99": percentile(all_lat, 99),
        },
        "traffic": {
            "per_min": [traffic.get(b, 0) for b in buckets],
            "count": len(received),
            # Rate tính trên số phút CÓ traffic; chia cho cả 60 phút cửa sổ sẽ
            # loãng ra gần 0 và làm threshold mất ý nghĩa.
            "rate_per_minute": round(len(received) / len(active), 2) if active else 0.0,
            "active_minutes": len(active),
        },
        "errors": {
            "received": len(received),
            "failed": len(failed),
            "rate_pct": round(len(failed) / len(received) * 100, 2) if received else 0.0,
            "breakdown": Counter(r.get("error_type", "unknown") for r in failed),
            # Mẫu số là request NHẬN trong chính phút đó, khớp định nghĩa panel
            # trong contract: count(request_failed) / count(request_received).
            "rate_per_min": [
                round(fail_by_min.get(b, 0) / traffic[b] * 100, 2) if traffic.get(b) else 0.0
                for b in buckets
            ],
            "failed_per_min": [fail_by_min.get(b, 0) for b in buckets],
        },
        "cost": {
            "per_min": [round(cost_by_min.get(b, 0.0), 6) for b in buckets],
            "total": round(sum(cost_by_min.values()), 6),
        },
        "tokens": {
            "in_per_min": [tin_by_min.get(b, 0) for b in buckets],
            "out_per_min": [tout_by_min.get(b, 0) for b in buckets],
            "in_total": sum(tin_by_min.values()),
            "out_total": sum(tout_by_min.values()),
        },
        "quality": {
            "per_min": [
                round(sum(qual_by_min[b]) / len(qual_by_min[b]), 4) if qual_by_min.get(b) else None
                for b in buckets
            ],
            "mean": round(sum(quality_all) / len(quality_all), 4) if quality_all else 0.0,
        },
    }


# --------------------------------------------------------------------------- svg

W, H = 560, 190
PAD_L, PAD_R, PAD_T, PAD_B = 52, 14, 14, 26
PLOT_W = W - PAD_L - PAD_R
PLOT_H = H - PAD_T - PAD_B


def _x(i: int, n: int) -> float:
    if n <= 1:
        return PAD_L + PLOT_W / 2
    return PAD_L + PLOT_W * i / (n - 1)


def _y(v: float, ymax: float) -> float:
    if ymax <= 0:
        return PAD_T + PLOT_H
    return PAD_T + PLOT_H * (1 - v / ymax)


def _fmt(v: float, unit: str) -> str:
    if unit == "usd":
        return f"{v:.4f}"
    if unit == "score_0_to_1":
        return f"{v:.2f}"
    if v >= 1000:
        return f"{v:,.0f}"
    return f"{v:.0f}" if float(v).is_integer() else f"{v:.2f}"


def _chrome(buckets: list[datetime], ymax: float, unit: str) -> list[str]:
    """Lưới ngang, nhãn trục y và hai mốc thời gian ở trục x."""
    out = []
    for i in range(5):
        v = ymax * i / 4
        y = _y(v, ymax)
        out.append(
            f'<line class="grid" x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}"/>'
        )
        out.append(
            f'<text class="tick" x="{PAD_L - 7}" y="{y + 3.5:.1f}" text-anchor="end">'
            f"{html.escape(_fmt(v, unit))}</text>"
        )
    out.append(
        f'<line class="axis" x1="{PAD_L}" y1="{PAD_T + PLOT_H}" '
        f'x2="{W - PAD_R}" y2="{PAD_T + PLOT_H}"/>'
    )
    if buckets:
        out.append(
            f'<text class="tick" x="{PAD_L}" y="{H - 8}" text-anchor="start">'
            f'{buckets[0].strftime("%H:%M")}</text>'
        )
        out.append(
            f'<text class="tick" x="{W - PAD_R}" y="{H - 8}" text-anchor="end">'
            f'{buckets[-1].strftime("%H:%M")}</text>'
        )
    return out


def _threshold(ymax: float, value: float, label: str) -> list[str]:
    if value is None or value > ymax:
        return []
    y = _y(value, ymax)
    return [
        f'<line class="thr" x1="{PAD_L}" y1="{y:.1f}" x2="{W - PAD_R}" y2="{y:.1f}"/>',
        f'<text class="thr-label" x="{W - PAD_R}" y="{y - 5:.1f}" text-anchor="end">'
        f"{html.escape(label)}</text>",
    ]


def line_chart(buckets, series, unit, threshold=None, thr_label="") -> str:
    values = [v for _, pts in series for v in pts if v is not None]
    ymax = max(values + ([threshold] if threshold is not None else []) + [1]) * 1.18
    n = len(buckets)
    parts = _chrome(buckets, ymax, unit)
    parts += _threshold(ymax, threshold, thr_label)

    for var, pts in series:
        seg, cur = [], []
        for i, v in enumerate(pts):
            if v is None:
                if len(cur) > 1:
                    seg.append(cur)
                cur = []
            else:
                cur.append((_x(i, n), _y(v, ymax)))
        if len(cur) > 1:
            seg.append(cur)
        for chunk in seg:
            d = " ".join(f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}" for j, (x, y) in enumerate(chunk))
            parts.append(f'<path class="line" style="stroke:var({var})" d="{d}"/>')
        for i, v in enumerate(pts):
            if v is None:
                continue
            x, y = _x(i, n), _y(v, ymax)
            parts.append(
                f'<circle class="dot" style="fill:var({var})" cx="{x:.1f}" cy="{y:.1f}" r="4">'
                f'<title>{buckets[i].strftime("%H:%M")} — {html.escape(_fmt(v, unit))} {html.escape(unit)}</title>'
                f"</circle>"
            )
    return f'<svg viewBox="0 0 {W} {H}" role="img" preserveAspectRatio="xMidYMid meet">' + "".join(parts) + "</svg>"


def bar_chart(buckets, groups, unit, threshold=None, thr_label="") -> str:
    """`groups` là list (css_var, list giá trị). Nhiều group => cột nhóm cạnh nhau."""
    values = [v for _, vals in groups for v in vals]
    ymax = max(values + ([threshold] if threshold is not None else []) + [1]) * 1.18
    n = len(buckets)
    parts = _chrome(buckets, ymax, unit)
    parts += _threshold(ymax, threshold, thr_label)

    slot = PLOT_W / max(n, 1)
    g = len(groups)
    # Chừa 2px nền giữa các cột cạnh nhau để hai mảng màu không dính vào nhau.
    bw = max(2.0, min(16.0, slot * 0.62 / g) - 2)
    base = PAD_T + PLOT_H

    for gi, (var, vals) in enumerate(groups):
        for i, v in enumerate(vals):
            if not v:
                continue
            y = _y(v, ymax)
            cx = PAD_L + slot * (i + 0.5)
            x = cx - (g * (bw + 2) - 2) / 2 + gi * (bw + 2)
            parts.append(
                f'<rect class="bar" style="fill:var({var})" x="{x:.1f}" y="{y:.1f}" '
                f'width="{bw:.1f}" height="{max(0.0, base - y):.1f}" rx="2">'
                f'<title>{buckets[i].strftime("%H:%M")} — {html.escape(_fmt(v, unit))} {html.escape(unit)}</title>'
                f"</rect>"
            )
    return f'<svg viewBox="0 0 {W} {H}" role="img" preserveAspectRatio="xMidYMid meet">' + "".join(parts) + "</svg>"


# --------------------------------------------------------------------------- html


def chip(ok: bool, text: str) -> str:
    mark = "✓" if ok else "!"
    cls = "ok" if ok else "bad"
    return f'<span class="chip {cls}"><span class="chip-mark" aria-hidden="true">{mark}</span>{html.escape(text)}</span>'


def legend(items: list[tuple[str, str]]) -> str:
    if len(items) < 2:
        return ""
    dots = "".join(
        f'<span class="lg"><span class="sw" style="background:var({v})"></span>{html.escape(l)}</span>'
        for v, l in items
    )
    return f'<div class="legend">{dots}</div>'


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows
    )
    return (
        '<details class="tbl"><summary>Xem dạng bảng</summary><div class="scroll">'
        f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div></details>"
    )


def panel(spec: dict, status: str, headline: str, sub: str, chart: str, lg: str, tbl: str) -> str:
    thr = spec["threshold"]
    op = "≤" if thr["operator"] == "lte" else "≥"
    return f"""<section class="panel">
  <header class="panel-head">
    <div class="panel-id">
      <h2>{html.escape(spec['title'])}</h2>
      <p class="meta">id <code>{html.escape(spec['id'])}</code> · đơn vị <b>{html.escape(spec['unit'])}</b>
         · threshold <b>{html.escape(thr['aggregation'])} {op} {thr['value']}</b></p>
    </div>
    {status}
  </header>
  <div class="headline"><span class="value">{headline}</span><span class="sub">{html.escape(sub)}</span></div>
  {lg}
  <div class="chart">{chart}</div>
  {tbl}
</section>"""


def build(cfg: dict, data: dict, start: datetime, end: datetime, log_path: Path) -> str:
    dash = cfg["dashboard"]
    specs = {p["id"]: p for p in dash["panels"]}
    b = data["buckets"]
    times = [x.strftime("%H:%M") for x in b]
    panels = []

    # --- latency ---------------------------------------------------------
    s = specs["latency"]
    lat, thr = data["latency"], s["threshold"]["value"]
    panels.append(
        panel(
            s,
            chip(lat["p95"] <= thr, f"P95 {lat['p95']:.0f} ms"),
            f'{lat["p95"]:.0f}<span class="unit">ms</span>',
            f'P50 {lat["p50"]:.0f} · P95 {lat["p95"]:.0f} · P99 {lat["p99"]:.0f} ms trên toàn cửa sổ',
            line_chart(b, [(SERIES[k][0], lat[k]) for k in ("q50", "q95", "q99")], "ms", thr, f"SLO {thr} ms"),
            legend([(SERIES[k][0], SERIES[k][1]) for k in ("q50", "q95", "q99")]),
            table(
                ["Phút", "P50 (ms)", "P95 (ms)", "P99 (ms)"],
                [
                    [times[i], *[("—" if lat[k][i] is None else f"{lat[k][i]:.0f}") for k in ("q50", "q95", "q99")]]
                    for i in range(len(b))
                    if lat["q50"][i] is not None
                ],
            ),
        )
    )

    # --- traffic ---------------------------------------------------------
    s, tr = specs["traffic"], data["traffic"]
    thr = s["threshold"]["value"]
    panels.append(
        panel(
            s,
            chip(tr["rate_per_minute"] >= thr, f'{tr["rate_per_minute"]:.2f} req/phút'),
            f'{tr["count"]}<span class="unit">req</span>',
            f'{tr["rate_per_minute"]:.2f} request/phút trên {tr["active_minutes"]} phút có traffic',
            bar_chart(b, [("--seq-2", tr["per_min"])], "requests_per_minute", thr, f"tối thiểu {thr}/phút"),
            "",
            table(["Phút", "Request nhận"], [[times[i], tr["per_min"][i]] for i in range(len(b)) if tr["per_min"][i]]),
        )
    )

    # --- errors ----------------------------------------------------------
    s, er = specs["errors"], data["errors"]
    thr = s["threshold"]["value"]
    brk = er["breakdown"]
    tr_pm = data["traffic"]["per_min"]
    panels.append(
        panel(
            s,
            chip(er["rate_pct"] <= thr, f'{er["rate_pct"]:.2f}%'),
            f'{er["rate_pct"]:.2f}<span class="unit">%</span>',
            f'{er["failed"]} lỗi / {er["received"]} request đã nhận',
            bar_chart(b, [("--status-critical", er["rate_per_min"])], "percent", thr, f"SLO {thr}%"),
            "",
            table(
                ["Phút", "Nhận", "Lỗi", "Error rate (%)"],
                [
                    [times[i], tr_pm[i], er["failed_per_min"][i], f'{er["rate_per_min"][i]:.2f}']
                    for i in range(len(b))
                    if tr_pm[i]
                ]
                + [["breakdown", "", k, v] for k, v in sorted(brk.items())],
            ),
        )
    )

    # --- cost ------------------------------------------------------------
    s, co = specs["cost"], data["cost"]
    thr = s["threshold"]["value"]
    panels.append(
        panel(
            s,
            chip(co["total"] <= thr, f'{co["total"]:.4f} USD'),
            f'{co["total"]:.4f}<span class="unit">USD</span>',
            f"tổng chi phí trong cửa sổ, ngân sách {thr} USD",
            line_chart(b, [("--seq-2", [v if v else None for v in co["per_min"]])], "usd"),
            "",
            table(["Phút", "Chi phí (USD)"], [[times[i], f'{co["per_min"][i]:.6f}'] for i in range(len(b)) if co["per_min"][i]]),
        )
    )

    # --- tokens ----------------------------------------------------------
    s, tk = specs["tokens"], data["tokens"]
    thr = s["threshold"]["value"]
    worst = max(tk["in_total"], tk["out_total"])
    panels.append(
        panel(
            s,
            chip(worst <= thr, f"tối đa {worst:,} token"),
            f'{tk["in_total"]:,}<span class="unit">in</span> · {tk["out_total"]:,}<span class="unit">out</span>',
            f"tổng theo từng field, trần {thr:,} token mỗi field",
            bar_chart(b, [("--cat-1", tk["in_per_min"]), ("--cat-2", tk["out_per_min"])], "tokens"),
            legend([("--cat-1", "tokens_in"), ("--cat-2", "tokens_out")]),
            table(
                ["Phút", "tokens_in", "tokens_out"],
                [[times[i], tk["in_per_min"][i], tk["out_per_min"][i]] for i in range(len(b)) if tk["in_per_min"][i]],
            ),
        )
    )

    # --- quality ---------------------------------------------------------
    s, qu = specs["quality"], data["quality"]
    thr = s["threshold"]["value"]
    panels.append(
        panel(
            s,
            chip(qu["mean"] >= thr, f'trung bình {qu["mean"]:.2f}'),
            f'{qu["mean"]:.2f}<span class="unit">/ 1.0</span>',
            f"quality proxy trung bình, sàn {thr}",
            line_chart(b, [("--seq-2", qu["per_min"])], "score_0_to_1", thr, f"sàn {thr}"),
            "",
            table(
                ["Phút", "Quality trung bình"],
                [[times[i], f'{qu["per_min"][i]:.2f}'] for i in range(len(b)) if qu["per_min"][i] is not None],
            ),
        )
    )

    return PAGE.format(
        title=html.escape(dash["title"]),
        window=dash["time_range_minutes"],
        refresh=dash["refresh_seconds"],
        t0=start.strftime("%Y-%m-%d %H:%M"),
        t1=end.strftime("%H:%M"),
        source=html.escape(str(log_path.relative_to(REPO_ROOT)).replace("\\", "/")),
        panels="\n".join(panels),
    )


PAGE = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title>
<style>
:root {{
  color-scheme: light;
  --page: #f9f9f7; --surface: #fcfcfb; --ink: #0b0b0b; --ink-2: #52514e;
  --muted: #898781; --grid: #e1e0d9; --axis: #c3c2b7; --ring: rgba(11,11,11,.10);
  --seq-1: #86b6ef; --seq-2: #2a78d6; --seq-3: #104281;
  --cat-1: #2a78d6; --cat-2: #eb6834;
  --status-good: #0ca30c; --status-critical: #d03b3b;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
    --page: #0d0d0d; --surface: #1a1a19; --ink: #fff; --ink-2: #c3c2b7;
    --muted: #898781; --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,.10);
    --seq-1: #b7d3f6; --seq-2: #5598e7; --seq-3: #1c5cab;
    --cat-1: #3987e5; --cat-2: #d95926;
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
  --page: #0d0d0d; --surface: #1a1a19; --ink: #fff; --ink-2: #c3c2b7;
  --muted: #898781; --grid: #2c2c2a; --axis: #383835; --ring: rgba(255,255,255,.10);
  --seq-1: #b7d3f6; --seq-2: #5598e7; --seq-3: #1c5cab;
  --cat-1: #3987e5; --cat-2: #d95926;
}}
* {{ box-sizing: border-box; }}
body {{ margin:0; padding:clamp(1rem,3vw,2.5rem); background:var(--page); color:var(--ink-2);
  font-family: system-ui,-apple-system,"Segoe UI",sans-serif; font-size:15px; line-height:1.55; }}
.wrap {{ max-width:78rem; margin:0 auto; display:flex; flex-direction:column; gap:1.5rem; }}
header.top {{ display:flex; flex-wrap:wrap; gap:.75rem 2rem; align-items:baseline;
  border-bottom:1px solid var(--grid); padding-bottom:1rem; }}
header.top h1 {{ margin:0; font-size:1.5rem; color:var(--ink); font-weight:650; letter-spacing:-.01em; }}
.chrome {{ display:flex; flex-wrap:wrap; gap:.4rem 1.5rem; font-size:.8125rem; color:var(--muted);
  font-variant-numeric:tabular-nums; }}
.chrome b {{ color:var(--ink-2); font-weight:600; }}
.grid-panels {{ display:grid; gap:1rem; grid-template-columns:1fr; }}
@media (min-width:64rem) {{ .grid-panels {{ grid-template-columns:1fr 1fr; }} }}
.panel {{ background:var(--surface); border:1px solid var(--ring); border-radius:6px;
  padding:1rem 1.15rem 1.15rem; display:flex; flex-direction:column; gap:.6rem; }}
.panel-head {{ display:flex; justify-content:space-between; align-items:flex-start; gap:1rem; }}
.panel h2 {{ margin:0; font-size:1rem; color:var(--ink); font-weight:650; }}
.meta {{ margin:.15rem 0 0; font-size:.75rem; color:var(--muted); font-variant-numeric:tabular-nums; }}
.meta code {{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:.9em; }}
.chip {{ display:inline-flex; align-items:center; gap:.35rem; white-space:nowrap;
  font-size:.75rem; font-weight:600; padding:.2rem .5rem; border-radius:3px;
  border:1px solid currentColor; font-variant-numeric:tabular-nums; }}
.chip.ok {{ color:var(--status-good); }}
.chip.bad {{ color:var(--status-critical); }}
.chip-mark {{ font-weight:700; }}
.headline {{ display:flex; flex-direction:column; gap:.1rem; }}
.headline .value {{ font-size:1.75rem; color:var(--ink); font-weight:600; line-height:1.1; }}
.headline .unit {{ font-size:.9rem; color:var(--muted); font-weight:500; margin-left:.25rem; }}
.headline .sub {{ font-size:.8125rem; color:var(--muted); }}
.legend {{ display:flex; flex-wrap:wrap; gap:.35rem 1rem; font-size:.75rem; color:var(--ink-2); }}
.lg {{ display:inline-flex; align-items:center; gap:.35rem; }}
.sw {{ width:11px; height:3px; border-radius:2px; display:inline-block; }}
.chart svg {{ width:100%; height:auto; display:block; }}
.grid {{ stroke:var(--grid); stroke-width:1; }}
.axis {{ stroke:var(--axis); stroke-width:1; }}
.tick {{ fill:var(--muted); font-size:9px; font-family:system-ui,sans-serif;
  font-variant-numeric:tabular-nums; }}
.thr {{ stroke:var(--status-critical); stroke-width:1.5; stroke-dasharray:5 4; opacity:.85; }}
.thr-label {{ fill:var(--status-critical); font-size:9px; font-weight:600;
  font-family:system-ui,sans-serif; }}
.line {{ fill:none; stroke-width:2; stroke-linecap:round; stroke-linejoin:round; }}
.dot {{ stroke:var(--surface); stroke-width:2; }}
.bar {{ stroke:var(--surface); stroke-width:0; }}
.tbl {{ margin-top:.2rem; }}
.tbl summary {{ cursor:pointer; font-size:.75rem; color:var(--muted); }}
.tbl summary:focus-visible {{ outline:2px solid var(--seq-2); outline-offset:2px; }}
.scroll {{ overflow-x:auto; margin-top:.5rem; }}
table {{ border-collapse:collapse; width:100%; font-size:.75rem;
  font-variant-numeric:tabular-nums; }}
th {{ text-align:left; color:var(--muted); font-weight:600; padding:.3rem .5rem;
  border-bottom:1px solid var(--axis); white-space:nowrap; }}
td {{ padding:.3rem .5rem; border-bottom:1px solid var(--grid); white-space:nowrap; }}
footer {{ font-size:.75rem; color:var(--muted); border-top:1px solid var(--grid); padding-top:.9rem; }}
</style></head><body><div class="wrap">
<header class="top">
  <h1>{title}</h1>
  <div class="chrome">
    <span>time range <b>{window} phút</b></span>
    <span>{t0} → {t1}</span>
    <span>refresh <b>{refresh}s</b></span>
    <span>nguồn <b>{source}</b></span>
  </div>
</header>
<div class="grid-panels">
{panels}
</div>
<footer>
  Sáu panel dựng bằng <code>scripts/build_dashboard.py</code>. Tên panel, đơn vị, threshold
  và cửa sổ thời gian đọc trực tiếp từ <code>config/dashboard.yaml</code> — không hard-code,
  nên ảnh chụp trang này khớp đúng contract mà <code>scripts/validate_dashboard.py</code> kiểm tra.
  Đường đứt đỏ là threshold/SLO line. Di chuột lên từng điểm hoặc cột để xem giá trị.
</footer>
</div></body></html>
"""


def main() -> int:
    configure_utf8_stdio()
    ap = argparse.ArgumentParser(description="Dựng dashboard 6 panel từ log")
    ap.add_argument("--logs", type=Path, default=DEFAULT_LOGS)
    ap.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    cfg = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    window = cfg["dashboard"]["time_range_minutes"]

    records, start, end = load_records(args.logs, window)
    buckets = minute_buckets(start, end)
    # Chỉ giữ các phút nằm trong khoảng thực sự có dữ liệu, tránh 60 cột rỗng.
    active = [i for i, x in enumerate(buckets) if any(_key(r["_ts"]) == x for r in records)]
    if active:
        buckets = buckets[active[0]: active[-1] + 1]

    data = compute(records, buckets)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(build(cfg, data, buckets[0], buckets[-1], args.logs), encoding="utf-8")

    print(f"Đã dựng dashboard: {args.out.relative_to(REPO_ROOT)}")
    print(f"  cửa sổ      : {buckets[0]:%Y-%m-%d %H:%M} → {buckets[-1]:%H:%M} ({len(buckets)} phút)")
    print(f"  request      : {data['traffic']['count']} nhận, {data['errors']['failed']} lỗi")
    print(f"  latency      : P50 {data['latency']['p50']:.0f} / P95 {data['latency']['p95']:.0f} / P99 {data['latency']['p99']:.0f} ms")
    print(f"  cost / tokens: {data['cost']['total']:.4f} USD · {data['tokens']['in_total']} in / {data['tokens']['out_total']} out")
    print(f"  quality      : {data['quality']['mean']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
