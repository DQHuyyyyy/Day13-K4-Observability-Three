# Báo cáo Day 13 Observability

## 1. Thông tin nhóm

- Tên nhóm: Three
- Repository URL: https://github.com/DQHuyyyyy/Day13-K4-Observability-Three
- Commit SHA cuối: `1260e306fed6624825cf06f34bf5c9573b3ac2a2` — commit chứa đầy đủ source và evidence. Nếu còn commit thêm sau dòng này, lấy giá trị mới bằng `git rev-parse HEAD` và nộp giá trị đó trên Codelabs.
- Thành viên và vai trò:

| Thành viên | Vai trò |
|---|---|
| Dương Quang Huy | Logging & PII |
| Nguyễn Tiến Đạt | Tracing & Prompt Versioning |
| Dương Văn Duy | Dashboard, SLO, Alert & Incident |

## 2. Kết quả kỹ thuật

- Điểm `validate_logs.py`: **30/100 (baseline, commit 5ba6472) → 100/100 (cuối)**
  - baseline: [`evidence/validate_logs_baseline.txt`](evidence/validate_logs_baseline.txt)
  - cuối: [`evidence/validate_logs_final.txt`](evidence/validate_logs_final.txt)
  - 144 log record, 39 correlation ID duy nhất, 0 PII leak, 0 record thiếu field bắt buộc, 0 record thiếu enrichment.
- Tổng số traces: **69** trên Langfuse (project `My Project`), `auth_check: True`, `/health` trả `tracing_enabled: true` — ảnh [`evidence/trace_list.png`](evidence/trace_list.png). Phân bố `prompt_source`: 38 `langfuse` (sau khi prompt được tạo), 30 `local-fallback` (trước đó), và 1 trace không có metadata — đó là request lỗi, `agent.run` ném exception trước khi kịp gọi `update_current_trace`. Yêu cầu ≥ 10 traces đã đạt.
- Số PII leak còn lại: **0** (theo detector độc lập trong `scripts/validate_logs.py`).
- Link/đường dẫn dashboard: **[`evidence/dashboard.html`](evidence/dashboard.html)** — mở bằng trình duyệt. Dựng bằng [`scripts/build_dashboard.py`](../scripts/build_dashboard.py) từ `data/logs.jsonl`. Contract tại [`config/dashboard.yaml`](../config/dashboard.yaml); kết quả validator tại [`evidence/validate_dashboard.txt`](evidence/validate_dashboard.txt) — `HỢP LỆ: 6/6 panel`.

Số liệu tổng trên toàn bộ log đã ghi: 35 request nhận / 34 thành công / 1 lỗi, cost 0.069267 USD, tokens 1044 in / 4409 out, quality trung bình 0.8412.

## 3. Logging và tracing

- **Evidence correlation ID**: [`evidence/log_correlation_id.json`](evidence/log_correlation_id.json).
  Correlation ID sinh trong [`app/middleware.py`](../app/middleware.py) theo định dạng `req-<8 hex>`, nhận lại `x-request-id` từ upstream nếu header khớp pattern an toàn `^[A-Za-z0-9_.:-]{1,64}$` — ID lạ bị loại vì có thể chứa ký tự điều khiển làm hỏng dòng log. ID được bind vào structlog contextvars và trả lại qua response header cùng `x-response-time-ms`.
  `clear_contextvars()` chạy ở đầu mỗi request: contextvars sống theo task, không xoá thì metadata của request trước rò sang request sau khi worker được tái sử dụng.

- **Evidence PII redaction**: [`evidence/log_pii_redacted.json`](evidence/log_pii_redacted.json) — email, số điện thoại VN và số thẻ trong `data/sample_queries.jsonl` đều xuất hiện dưới dạng `[REDACTED_*]`.
  Hai điểm triển khai đáng chú ý:
  1. `scrub_event` đặt **sau** `format_exc_info` và **trước** `JsonlFileProcessor` trong pipeline structlog — redact trước khi render, và quét được cả traceback. Nếu đặt sau bước ghi file thì log trên đĩa đã lộ rồi.
  2. `scrub_event` quét **đệ quy mọi giá trị chuỗi**, không chỉ `payload`, vì PII còn có thể lọt vào exception message hay field nhóm thêm sau này. Các khoá hệ thống (`ts`, `level`, `correlation_id`, `user_id_hash`, `service`) được loại trừ để regex không cắt nát timestamp.
  3. `hash_user_id` thêm tiền tố `uh_`: một digest 12 ký tự hex có thể ngẫu nhiên toàn chữ số và bị chính detector CCCD (`\b\d{12}\b`) báo nhầm là leak.

- **Evidence trace waterfall**: trace `76b1fe4d75a4364c7575064c575b4974` (session `pv-baseline`) — ảnh [`evidence/trace_waterfall.png`](evidence/trace_waterfall.png). Danh sách traces: [`evidence/trace_list.png`](evidence/trace_list.png).

- **Giải thích một span đáng chú ý**: span `retrieval_completed` (`tool_name=mock_rag.retrieve`). Nhóm bổ sung span này vì latency tổng không trả lời được câu hỏi "chậm ở đâu". Trong sự cố, span này = 2500 ms trên **cả 10** request bị ảnh hưởng trong khi span `llm_completed` giữ nguyên 150–164 ms — chính con số này khoanh vùng root cause chỉ trong một truy vấn log. Ở trạng thái bình thường span này = 0 ms.

## 4. Prompt versioning

Evidence đầy đủ: [`evidence/prompt_versioning.txt`](evidence/prompt_versioning.txt)

- **Prompt name**: `day13-chat` (text prompt, giữ đủ ba biến `{{feature}}`, `{{docs}}`, `{{message}}`)
- **Version/label baseline**: version **1**, labels `baseline` + `production`
- **Version/label candidate**: version **2**, label `candidate` — thay đổi nhỏ về độ dài: thêm dòng `Answer in at most 3 sentences. Cite the retrieved context.`
- **Trace ID của mỗi version**:

| session | trace ID | label | version | source |
|---|---|---|---|---|
| `pv-baseline` | `76b1fe4d75a4364c7575064c575b4974` | `baseline` | 1 | `langfuse` |
| `pv-candidate` | `bc2fcd3b785704628fc6b7c2aaf68a03` | `candidate` | 2 | `langfuse` |
| `pv-production-v2` | `77e0327f594f97133919db20208f18b2` | `production` | 2 | `langfuse` |
| `pv-production-rollback-v1` | `1defc045c57bf3dbadb70aa679575011` | `production` | 1 | `langfuse` |

Cả bốn dùng **cùng một input**: `"Explain why metrics traces and logs work together."` (feature `monitoring`).

- **Bằng chứng đổi label / rollback**: hai dòng cuối bảng, đọc theo thứ tự thời gian. Cùng label `production`, hai trace, hai version khác nhau: chuyển `production` sang v2 → trace ghi `prompt_version=2`; rollback `production` về v1 → trace ghi `prompt_version=1`. Không có dòng code nào thay đổi giữa hai lần chạy — chỉ label trên Langfuse. Ảnh: [`evidence/prompt_rollback.png`](evidence/prompt_rollback.png).

- **Ảnh hai prompt version**: [`evidence/prompt_version1.png`](evidence/prompt_version1.png) và [`evidence/prompt_version2.png`](evidence/prompt_version2.png). Mỗi ảnh đều thấy cột version bên trái (v1 `production`+`baseline`, v2 `latest`+`candidate`) và nội dung prompt bên phải — v2 có thêm dòng ràng buộc độ dài, còn cả hai giữ đủ ba biến `{{feature}}`, `{{docs}}`, `{{message}}` theo contract.
- **Ảnh trace gắn đúng version/label**: [`evidence/trace_prompt_metadata.png`](evidence/trace_prompt_metadata.png) — tab Metadata của trace, đọc được `prompt_name`, `prompt_label`, `prompt_version`, `prompt_source=langfuse`.

### Hai điều học được từ phần này

**1. App không được giả vờ đã lấy được prompt managed.** Trước khi prompt tồn tại trên Langfuse, `get_prompt` trả 404 và [`app/prompt_management.py`](../app/prompt_management.py) rơi vào nhánh fallback, ghi thẳng `prompt_source=local-fallback` / `prompt_version=local-v1` vào trace metadata. 30 trace đầu tiên đều như vậy. Nhờ ghi trung thực mà phát hiện được ngay là prompt chưa được tạo; nếu fallback im lặng ghi `version=1` thì cả nhóm đã tưởng prompt versioning đang chạy đúng.

**2. Fallback không được cache và điều đó tốn latency thật.** Khi prompt chưa tồn tại, mỗi request đều gọi lại Langfuse và nhận 404 → latency p50 tăng từ 152 ms lên **1083 ms**. Sau khi tạo prompt, `cache_ttl_seconds=60` phát huy tác dụng: chỉ request đầu tiên trong mỗi cửa sổ 60 giây chịu chi phí fetch. Đo được trong đợt chạy healthy cuối:

| request | total_ms | retrieval_ms | llm_ms | phần còn lại (prompt fetch) |
|---|---:|---:|---:|---:|
| req-40c1778e (đầu tiên) | 1069 | 0 | 150 | ~917 |
| 9 request sau | 151–159 | 0 | 150 | ~2 |

Đây cũng là lý do p95 của pha healthy là 1069 ms trong khi p50 chỉ 152 ms — **một request cold-start trên tổng số 10 là đủ để chiếm luôn p95**. Bài học về percentile: ở lưu lượng thấp, p95 rất nhạy với cold start, nên cửa sổ đo và số mẫu tối thiểu phải được ghi rõ trong định nghĩa SLO.

## 5. Dashboard, SLO và alerts

- Kết quả `validate_dashboard.py`: `HỢP LỆ: 6/6 panel có trong dashboard contract.` — [`evidence/validate_dashboard.txt`](evidence/validate_dashboard.txt)
- Evidence dashboard: **[`evidence/dashboard.html`](evidence/dashboard.html)** (bản chạy được) và ảnh chụp [`evidence/dashboard.png`](evidence/dashboard.png), dựng bằng [`scripts/build_dashboard.py`](../scripts/build_dashboard.py).

  Điểm quan trọng của cách dựng này: script **đọc tên panel, đơn vị, threshold và `time_range_minutes` trực tiếp từ `config/dashboard.yaml`**, không hard-code. Nên dashboard không thể lệch contract mà validator vẫn báo hợp lệ — hai thứ dùng chung một nguồn sự thật. Trang hiển thị đủ time range (60 phút), đơn vị từng panel, threshold/SLO line dạng đường đứt, và một chip trạng thái đạt/vi phạm cho mỗi panel.

  Trong cửa sổ đang chụp, panel **Error rate** báo **vi phạm thật**: 1 lỗi / 35 request = **2.86%**, vượt SLO 2%. Lỗi đó là `RuntimeError: Vector store timeout` sinh ra khi bật incident `tool_fail` để kiểm chứng `error_rate_pct` — log gốc tại [`evidence/log_request_failed.json`](evidence/log_request_failed.json).

  Sáu panel dùng bảng màu đã chạy qua validator ở cả light lẫn dark: latency dùng thang xanh một sắc theo bậc (P50 → P99 sáng sang tối, vì thứ tự phân vị là thứ tự độ lớn chứ không phải bốn danh mục rời rạc), token dùng hai màu categorical, error dùng màu status kèm ký hiệu `!` chứ không chỉ dựa vào màu. Mỗi panel kèm bảng số liệu để đọc được khi không phân biệt được màu.
- SLO đã chọn và lý do: xem [`config/slo.yaml`](../config/slo.yaml).
  - `latency_p95_ms ≤ 3000`, đạt 99.5% / 28 ngày. **Chọn p95 chứ không phải trung bình**: trong sự cố này p50 vẫn là 156 ms trong khi p95 lên 2667 ms — trung bình sẽ bị phần dưới kéo phẳng và giấu mất đúng nhóm người dùng đang chịu ảnh hưởng.
  - `error_rate_pct ≤ 2`, đạt 99.0%. Cần sàn tối thiểu 20 request mỗi cửa sổ, nếu không 1 lỗi trên 10 request đã thành 10%.
  - `daily_cost_usd ≤ 2.5` — ngân sách cứng cho môi trường lab.
  - `quality_score_avg ≥ 0.75` — chỉ theo dõi xu hướng, **không gắn alert**.
- Alert rules và runbook: [`config/alert_rules.yaml`](../config/alert_rules.yaml) + [`docs/alerts.md`](../docs/alerts.md).

| Alert | Severity | Điều kiện | Duration | Owner |
|---|---|---|---|---|
| `chat_latency_p95_breach` | P2 | p95(latency_ms) > 3000 ms | 5m | Dương Văn Duy |
| `chat_error_rate_breach` | P1 | error rate > 2% | 5m | Dương Quang Huy |
| `chat_cost_per_request_spike` | P3 | cost/phút > 2× median 1h **và** traffic không tăng > 20% | 15m | Nguyễn Tiến Đạt |

Ba quyết định thiết kế: (a) alert đặt theo **triệu chứng** người dùng cảm nhận được chứ không theo tên nguyên nhân nội bộ — đặt alert tên `rag_slow` sẽ bỏ sót mọi nguyên nhân khác gây cùng triệu chứng chậm; (b) alert nào cũng có duration, không có duration thì mỗi gai nhọn tức thời đều thành page và người trực sẽ học cách phớt lờ; (c) alert chi phí dùng **điều kiện kép** với traffic, vì chi phí tăng do đông người dùng là bình thường, chỉ chi phí tăng khi traffic đứng yên mới là hồi quy đơn giá.

## 6. Điều tra challenge

- **Challenge ID**: `day13-k4-observability-v1` (cohort K4, incident `rag_slow`, seed 1304, `affected_feature: monitoring`, `latency_threshold_ms: 2000`)
- Evidence đầy đủ: [`evidence/challenge_investigation.txt`](evidence/challenge_investigation.txt)

### Triệu chứng từ metrics

| Pha | n | p50 | p95 | p99 |
|---|---:|---:|---:|---:|
| Healthy (`sample_queries.jsonl`) | 10 | 152 ms | 1069 ms¹ | 1069 ms¹ |
| Challenge, incident bật | 10 | 2654 ms | **2663 ms** | 2663 ms |
| Challenge, sau khi tắt incident | 5 | 155 ms | 158 ms | 158 ms |

¹ p95 pha healthy bị đẩy lên bởi đúng **một** request cold-start phải fetch prompt từ Langfuse (~917 ms). 9 request còn lại nằm trong 151–159 ms. Xem mục 4.

So mốc ổn định với mốc ổn định (152 ms → 2654 ms), p50 tăng **17×**, vượt ngưỡng 2000 ms của challenge. Điểm đáng chú ý: trong pha sự cố **p50 và p95 gần bằng nhau** — nghĩa là sự cố ảnh hưởng *mọi* request thuộc feature `monitoring`, không phải một phần đuôi. Đây là dấu hiệu phân biệt quan trọng: đuôi dài lệch riêng p95 thường là contention hoặc retry, còn cả phân phối dịch đều như thế này là một bước xử lý có thời lượng cố định.

Chênh lệch quan trọng thứ hai: latency client đo được lên tới **13 350 ms**, trong khi log server ghi `latency_ms` chỉ 2663 ms. Khoảng cách 5× này chính là manh mối dẫn tới tầng nguyên nhân thứ hai.

### Trace / span liên quan

`correlation_id` của các request chậm nhất: `req-1f5cb362`, `req-17cdd619`, `req-d845dd9f`, `req-8d7155d1`, `req-1be8240e`.

Phân rã theo span (từ event `retrieval_completed` và `llm_completed`):

| correlation_id | retrieval_ms | llm_ms | total_ms |
|---|---:|---:|---:|
| req-1f5cb362 | 2500 | 156 | 2663 |
| req-17cdd619 | 2500 | 152 | 2659 |
| req-d845dd9f | 2500 | 150 | 2656 |
| req-8d7155d1 | 2500 | 151 | 2655 |
| req-1be8240e | 2500 | 150 | 2654 |

Span retrieval chiếm **94.2%** tổng latency. Span LLM không đổi so với pha healthy. Trên 10 request healthy, `retrieval_ms = 0` ở cả 10.

### Log line liên quan

```
2026-08-11T08:36:54.661503Z  incident_enabled   rag_slow
2026-08-11T08:37:24.201169Z  incident_disabled  rag_slow
```

Mọi `response_sent` nằm giữa hai mốc này và có `feature=monitoring` đều mang `payload.retrieval_ms = 2500`; mọi request ngoài khoảng đó có `retrieval_ms = 0`. Tương quan thời gian là tuyệt đối, không có ngoại lệ.

### Root cause

Có **hai tầng**, và tầng thứ hai mới là thứ khiến người dùng chịu 13 giây thay vì 2,7 giây.

**Tầng 1 — nguồn gây chậm.** [`app/mock_rag.py:18`](../app/mock_rag.py#L18): khi cờ `rag_slow` bật, `retrieve()` chạy `time.sleep(2.5)` trước khi trả document. Đây là 2500 ms đo được trên span retrieval, chiếm 94.2% latency mỗi request.

**Tầng 2 — cơ chế khuếch đại.** Handler `/chat` trong [`app/main.py:46`](../app/main.py#L46) khai báo `async def`, nhưng `retrieve()` là hàm đồng bộ dùng `time.sleep` — một lời gọi **chặn** chạy thẳng trên event loop. Event loop bị giữ suốt 2,5 giây nên không request nào khác được xử lý trong lúc đó: 5 request đồng thời bị xếp hàng tuần tự.

Bằng chứng thực nghiệm (cùng 5 query, incident vẫn bật, chỉ đổi mức đồng thời):

| Mức đồng thời | Latency mỗi request | Tổng wall time |
|---|---|---|
| `--concurrency 5` | 8 010 – 13 350 ms | ~13,3 s |
| `--concurrency 1` | 2 665 – 2 669 ms | 14,3 s |

Tổng thời gian **gần như bằng nhau** ở cả hai mức. Nếu server thực sự xử lý song song thì concurrency 5 phải nhanh hơn khoảng 5 lần; ở đây throughput không đổi, chứng tỏ mức song song thực tế bằng 1. Con số 13,3 s cũng khớp chính xác với 5 × 2,66 s.

Dấu hiệu này còn tồn tại cả khi hệ thống khoẻ: ở pha recovery, 5 request đồng thời trả về lần lượt tại 356 / 816 / 817 / 819 / 819 ms thay vì cùng khoảng 155 ms — vẫn là xếp hàng, chỉ là 150 ms mỗi lượt nên không ai để ý. Nói cách khác, lỗi kiến trúc này đã có sẵn từ trước; sự cố `rag_slow` chỉ làm nó lộ ra.

Lời gọi Langfuse `get_prompt` cũng nằm trên cùng đường chặn đó, nên khi prompt chưa tồn tại, mỗi request cộng thêm ~900 ms vào thời gian giữ event loop — cùng một lỗi kiến trúc, hai nguồn gây chậm khác nhau.

### Fix action

1. **Ngay lập tức**: tắt cờ sự cố — `python scripts/inject_incident.py --disable`. Đã xác nhận: p95 về 156 ms.
2. **Sửa cơ chế khuếch đại** (nguyên nhân thực sự): không để lời gọi chặn chạy trên event loop. Đổi `async def chat` thành `def chat` để FastAPI tự đẩy handler sang threadpool, hoặc giữ `async def` và bọc lời gọi chặn:
   ```python
   from starlette.concurrency import run_in_threadpool
   docs = await run_in_threadpool(retrieve, message)
   ```
   Sau khi sửa, 5 request đồng thời phải hoàn tất trong ~2,7 s thay vì ~13,3 s ngay cả khi retrieval vẫn chậm.
3. **Đặt timeout cho retrieval** (ví dụ 1000 ms) và trả lời bằng fallback không có context khi quá hạn — đổi chất lượng lấy latency thay vì để người dùng chờ vô hạn.

### Preventive measure

1. **Alert `chat_latency_p95_breach`** (P2, p95 > 3000 ms trong 5 phút) sẽ bắt được đúng lớp sự cố này trước khi người dùng phàn nàn.
2. **Giữ span-level timing làm tài sản lâu dài.** `retrieval_ms` và `llm_ms` là thứ biến cuộc điều tra này từ "đoán" thành một truy vấn log duy nhất. Không có nó, latency tổng 2667 ms không nói được là lỗi ở RAG hay LLM.
3. **Load test phải chạy ở mức đồng thời > 1 trong CI.** Lỗi chặn event loop hoàn toàn vô hình ở concurrency 1 — chính vì vậy nó đã tồn tại sẵn trong code mà không ai phát hiện.
4. **Thêm kiểm tra tự động chặn lời gọi chặn trong handler async**, ví dụ chạy asyncio ở chế độ debug (`PYTHONASYNCIODEBUG=1`) trong môi trường test để cảnh báo khi một callback giữ event loop quá lâu.
5. **Flush trace khi app shutdown.** Trong lúc thu thập evidence, bốn trace đầu tiên đã **mất trắng** vì SDK gom trace theo batch còn process bị dừng ngay sau request. Nhóm đã thêm handler `shutdown` gọi `flush_tracing()` trong [`app/main.py`](../app/main.py). Không có nó, mỗi lần restart hoặc deploy tạo một khoảng mù observability đúng vào thời điểm dễ xảy ra sự cố nhất — và tệ hơn, khoảng mù đó im lặng.

## 7. Đóng góp cá nhân

Bảng dưới ghi theo **nội dung commit thật**, không theo phân vai dự kiến — vì hai thứ đã lệch nhau trong lúc merge (xem ghi chú cuối mục). Repo: `https://github.com/DQHuyyyyy/Day13-K4-Observability-Three`

| Thành viên | Phần việc (theo đúng file trong commit) | Commit | Điều đã học |
|---|---|---|---|
| **Dương Quang Huy**<br/>`Quang Huy` | **Logging, correlation ID và PII.** `app/middleware.py` (sinh/nhận correlation ID, clear + bind contextvars, response header), `app/logging_config.py` (đăng ký `scrub_event`, quét đệ quy), `app/pii.py` (pattern hộ chiếu/địa chỉ VN/số tài khoản, tiền tố `uh_`), `app/metrics.py`. Sau đó merge nhánh `dat` và `duy`, và bổ sung `app/agent.py` + `app/main.py`. | [`a59257b`](https://github.com/DQHuyyyyy/Day13-K4-Observability-Three/commit/a59257b3acc93237726379c4fb54f31112f62486) Check Point 1<br/>[`17ebfae`](https://github.com/DQHuyyyyy/Day13-K4-Observability-Three/commit/17ebfae) merge branch dat<br/>[`15f4bd7`](https://github.com/DQHuyyyyy/Day13-K4-Observability-Three/commit/15f4bd7) merge Duy<br/>[`375ec97`](https://github.com/DQHuyyyyy/Day13-K4-Observability-Three/commit/375ec971ec08fc45cf3035a9280e65674fb3b34a) add function | Thứ tự processor trong pipeline log quyết định tất cả: `scrub_event` phải đứng **sau** `format_exc_info` để quét được cả traceback, và **trước** bước ghi file — đặt sau bước ghi thì dữ liệu trên đĩa đã lộ và không thu hồi được. Học thêm rằng chính bộ detector PII có thể báo nhầm: digest 12 ký tự hex có thể ngẫu nhiên toàn chữ số và khớp regex CCCD, nên phải thêm tiền tố `uh_` để phá `\b`. |
| **Nguyễn Tiến Đạt**<br/>`nguyentiendat` | **Tracing, prompt versioning, SLO/alert và dashboard.** `app/tracing.py` (`flush_tracing()`), shutdown handler trong `app/main.py`, cấu hình Langfuse + tạo prompt `day13-chat` v1/v2 và rollback label. Kèm `config/slo.yaml`, `config/alert_rules.yaml`, `docs/alerts.md`, `docs/blueprint-template.md`, `scripts/build_dashboard.py` và `submission/REPORT.md`. Sửa lỗi nhân đôi `app/main.py`. | [`d0aeabf`](https://github.com/DQHuyyyyy/Day13-K4-Observability-Three/commit/d0aeabf891a95b2bbdde1820aacd28f02f00cb2a) checkpoint 2<br/>[`9ea2943`](https://github.com/DQHuyyyyy/Day13-K4-Observability-Three/commit/9ea294328248a2bd26bd11e29f4730fb71be3e67) fix main.py<br/>[`d913c83`](https://github.com/DQHuyyyyy/Day13-K4-Observability-Three/commit/d913c83d7f93004deb8f47dce324e590fb8a76c3) dashboard 6 panel | Một hệ thống quan sát phải **trung thực về chính nó**. Khi prompt chưa tồn tại, app ghi `prompt_source=local-fallback` thay vì giả vờ `version=1` — nhờ vậy phát hiện ngay sau 30 trace rằng prompt chưa được tạo. Ngược lại, thứ *không* được ghi lại thì không tồn tại: 4 trace đầu mất trắng vì SDK gửi theo batch mà process dừng trước khi flush, tạo một khoảng mù im lặng đúng lúc restart. |
| **Dương Văn Duy**<br/>`Elemental-Sight` | **Span timing và error rate.** Span log `retrieval_completed` / `llm_completed` trong `app/agent.py`, đưa `retrieval_ms` / `llm_ms` vào `AgentResult` và vào payload `response_sent` của `app/main.py`, hàm `error_rate_pct()` trong `app/metrics.py` cùng `tests/test_metrics.py`. | [`49c7e9c`](https://github.com/DQHuyyyyy/Day13-K4-Observability-Three/commit/49c7e9c3a60b9a3e779fad9d1b7f7ec90a47e91d) Hoàn thiện CP3<br/>[`0dae878`](https://github.com/DQHuyyyyy/Day13-K4-Observability-Three/commit/0dae878ba0165d156a1738233345004e4c08d803) Update Checkpoint 3 | Latency tổng chỉ nói “chậm”, span mới nói “chậm ở đâu”: `retrieval_ms=2500` so với `llm_ms=150` khoanh vùng root cause chỉ trong một truy vấn log. Về metric, mẫu số quan trọng hơn tử số — `error_rate_pct` phải chia cho **tổng request đã nhận**, vì `TRAFFIC` chỉ tăng ở cuối `LabAgent.run` nên request lỗi không bao giờ được đếm; lấy `TRAFFIC` làm mẫu số sẽ chia cho 0 đúng lúc mọi request đều hỏng. |

### Ghi chú về sự lệch giữa phân vai và commit

Phân vai ở mục 1 và nội dung commit không trùng khớp hoàn toàn: `config/slo.yaml`, `config/alert_rules.yaml`, `docs/alerts.md` và `scripts/build_dashboard.py` thuộc mảng Dashboard/SLO/Alert của Dương Văn Duy nhưng nằm trong commit của Nguyễn Tiến Đạt (`d0aeabf`, `d913c83`), do thứ tự merge giữa các nhánh. Bảng trên ghi theo Git để khớp yêu cầu đối chiếu của RUBRIC B2; ai trình bày phần nào lúc demo thì theo phân vai ở mục 1.

Một commit đáng rút kinh nghiệm: `375ec97` đặt tên “add function” nhưng thực chất dán trùng toàn bộ `app/main.py` (256 dòng = 128 dòng lặp hai lần), khiến `from __future__ import annotations` xuất hiện lại ở dòng 129 và app không import được — toàn bộ test hỏng ngay ở bước collection. Validator không bắt được lỗi này vì nó không chạy app; chỉ `pytest` và code review mới thấy. Đã sửa ở `9ea2943`.

## 8. Danh mục evidence

Đầy đủ: 7 ảnh chụp và 9 file dữ liệu sinh trực tiếp từ `data/logs.jsonl` và Langfuse API.

| File | Nội dung |
|---|---|
| [`validate_logs_baseline.txt`](evidence/validate_logs_baseline.txt) | 30/100 ở commit gốc |
| [`validate_logs_final.txt`](evidence/validate_logs_final.txt) | 100/100 · 144 record · 39 correlation ID · 0 PII leak |
| [`validate_dashboard.txt`](evidence/validate_dashboard.txt) | `HỢP LỆ: 6/6 panel` |
| [`log_correlation_id.json`](evidence/log_correlation_id.json) | Log có correlation ID và đủ enrichment |
| [`log_pii_redacted.json`](evidence/log_pii_redacted.json) | Email / số điện thoại / số thẻ đã `[REDACTED_*]` |
| [`log_request_failed.json`](evidence/log_request_failed.json) | Log lỗi làm error rate chạm 2.86% |
| [`challenge_investigation.txt`](evidence/challenge_investigation.txt) | Phân rã latency theo span, percentile ba pha |
| [`prompt_versioning.txt`](evidence/prompt_versioning.txt) | 4 trace ID kèm label / version / source |
| [`dashboard.html`](evidence/dashboard.html) · [`dashboard.png`](evidence/dashboard.png) | Dashboard 6 panel, bản chạy được và ảnh chụp |
| [`trace_list.png`](evidence/trace_list.png) | Danh sách traces — 11 dòng hiển thị, `Total ≈ 69`, có cột Metadata |
| [`trace_waterfall.png`](evidence/trace_waterfall.png) | Waterfall trace `76b1fe4d…` — span cha 1.15s + generation con |
| [`trace_prompt_metadata.png`](evidence/trace_prompt_metadata.png) | `prompt_name` / `prompt_label` / `prompt_version` / `prompt_source=langfuse` |
| [`prompt_version1.png`](evidence/prompt_version1.png) · [`prompt_version2.png`](evidence/prompt_version2.png) | Hai version của `day13-chat` kèm label và nội dung |
| [`prompt_rollback.png`](evidence/prompt_rollback.png) | Label `production` ở version 2 — trạng thái trước rollback |

Việc duy nhất còn lại: điền **commit SHA cuối** ở mục 1 bằng `git rev-parse HEAD`, và điền cột *Điều đã học* ở mục 7 nếu muốn viết lại theo lời của mình.
