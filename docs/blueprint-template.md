# Khung thiết kế Observability

Dùng khung này trước khi triển khai, sau đó chuyển kết quả cuối sang `submission/REPORT.md`.

## Người dùng và luồng chính

- **Ai gửi request?** Client gọi `POST /chat` với `user_id`, `session_id`, `feature`, `message`. Trong lab, client là `scripts/load_test.py`.
- **Request đi qua những thành phần nào?**
  `CorrelationIdMiddleware` → handler `/chat` → `LabAgent.run` → `mock_rag.retrieve` (RAG) → `prompt_management.resolve_prompt` (Langfuse) → `FakeLLM.generate` → `metrics.record_request` → response.
- **Correlation ID được tạo và truyền ở đâu?** Tạo trong middleware (`req-<8 hex>`), hoặc nhận lại từ header `x-request-id` nếu upstream gửi ID đúng định dạng an toàn. Truyền đi bằng structlog contextvars nên mọi log trong cùng request tự mang ID mà không phải truyền tay qua từng hàm. Trả về client qua response header `x-request-id`.

## Tín hiệu quan sát

| Thành phần | Log cần có | Metric cần có | Span cần có |
|---|---|---|---|
| API | `request_received`, `response_sent`, `request_failed` — kèm `correlation_id`, `user_id_hash`, `session_id`, `feature`, `model`, `env` | traffic, latency p50/p95/p99, error rate theo `error_type` | span gốc của request |
| Retrieval | `retrieval_completed` với `tool_name`, `latency_ms`, `doc_count` | latency riêng của retrieval, tỉ lệ truy xuất rỗng | span con `mock_rag.retrieve` |
| LLM | `llm_completed` với `tool_name` (model), `latency_ms`, `tokens_in`, `tokens_out` | token in/out, cost, quality proxy | generation span kèm `prompt_name` / `prompt_label` / `prompt_version` |

Nguyên tắc: **latency phải tách được theo từng bước**. Latency tổng chỉ nói "chậm", span mới nói "chậm ở đâu" — trong sự cố `rag_slow` chính `retrieval_ms = 2500` so với `llm_ms = 150` là thứ chốt được root cause.

## SLO và alert

| SLI | Mục tiêu | Cửa sổ đo | Alert |
|---|---:|---|---|
| Latency P95 | ≤ 3000 ms, đạt 99.5% | 28 ngày | `chat_latency_p95_breach` — P2, duy trì 5m |
| Error rate | ≤ 2%, đạt 99.0% | 28 ngày | `chat_error_rate_breach` — P1, duy trì 5m |
| Cost | ≤ 2.5 USD/ngày | 28 ngày | `chat_cost_per_request_spike` — P3, duy trì 15m, kèm điều kiện traffic không tăng |
| Quality | ≥ 0.75 trung bình, đạt 95% | 28 ngày | không alert — heuristic quá nhiễu để page người trực |

## Rủi ro dữ liệu

- **PII có thể xuất hiện ở đâu?** Chủ yếu trong `message` do người dùng nhập (email, số điện thoại, số thẻ, CCCD, địa chỉ). Ngoài ra còn có `user_id` thô, exception message khi lỗi xảy ra giữa lúc đang xử lý nội dung người dùng, và bản xem trước câu trả lời nếu model nhắc lại thông tin đã nhận.
- **Dữ liệu nào được phép ghi vào log?** Chỉ metadata và bản tóm tắt đã làm sạch: `user_id_hash` (không bao giờ ghi `user_id` thô), `session_id`, `feature`, `model`, `env`, các số đo, và `message_preview` giới hạn 80 ký tự đã qua redaction.
- **Redaction diễn ra trước bước nào?** Trước mọi bước ghi ra ngoài. Trong pipeline structlog, `scrub_event` đứng sau `format_exc_info` (để quét được cả traceback) và ngay trước `JsonlFileProcessor`. Đặt sau bước ghi file thì dữ liệu trên đĩa đã lộ và không thu hồi được.
