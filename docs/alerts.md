# Template Alert và Runbook

Mỗi alert phải dựa trên triệu chứng người dùng hoặc SLO, không dựa trực tiếp vào tên implementation nội bộ.

Ba alert dưới đây bám theo bốn SLI trong [`config/slo.yaml`](../config/slo.yaml) và đọc từ cùng một nguồn với dashboard là `data/logs.jsonl`. Quality proxy cố ý **không** được gắn alert — xem phần cuối file.

## Alert 1

- Tên: `chat_latency_p95_breach`
- Severity: P2
- SLI/SLO liên quan: `latency_p95_ms`, mục tiêu 3000 ms, 99.5% trong cửa sổ 28 ngày.
- Điều kiện và thời gian duy trì: `p95(latency_ms)` trên event `response_sent` vượt 3000 ms và **duy trì liên tục 5 phút**. Duration 5 phút để một burst ngắn hoặc một cold start không tạo page.
- Ảnh hưởng tới người dùng: câu trả lời chậm thấy rõ; ở mức nghiêm trọng client sẽ timeout trước khi có response.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Latency percentiles**, đối chiếu p50 với p95. p50 phẳng còn p95 vọt nghĩa là chỉ một phần request bị ảnh hưởng — nghi ngờ một dependency chậm chứ không phải toàn hệ thống quá tải.
  2. Lọc `event=="response_sent"` trong log, so `payload.retrieval_ms` với `payload.llm_ms` để biết span nào chiếm phần lớn latency.
  3. Mở trace của một `correlation_id` chậm nhất và xác nhận đúng span đó dài bất thường.
- Mitigation tạm thời: đặt timeout cứng cho bước retrieval và trả lời bằng fallback không có context khi timeout, đổi lấy chất lượng thấp hơn nhưng giữ được latency.
- Owner: Duy

## Alert 2

- Tên: `chat_error_rate_breach`
- Severity: P1
- SLI/SLO liên quan: `error_rate_pct`, mục tiêu ≤ 2%, 99.0% trong cửa sổ 28 ngày.
- Điều kiện và thời gian duy trì: tỉ lệ `request_failed / request_received` vượt 2% và **duy trì 5 phút**. Ở lưu lượng thấp cần thêm sàn tối thiểu 20 request trong cửa sổ, nếu không 1 lỗi trên 10 request đã thành 10% và gây báo động giả.
- Ảnh hưởng tới người dùng: request trả HTTP 500, người dùng không nhận được câu trả lời nào.
- Ba bước kiểm tra đầu tiên:
  1. Mở panel **Error rate and breakdown**, xem `error_type` nào chiếm đa số — một loại lỗi duy nhất trỏ tới một dependency, nhiều loại trỏ tới sự cố hạ tầng.
  2. Lấy `correlation_id` của một `request_failed` và đọc `payload.detail`.
  3. Kiểm tra `feature` và `session_id` của các request lỗi: nếu tập trung vào một feature thì phạm vi ảnh hưởng hẹp hơn.
- Mitigation tạm thời: nếu lỗi đến từ vector store, cho phép trả lời không có RAG context thay vì fail toàn bộ request.
- Owner: Huy

## Alert 3

- Tên: `chat_cost_per_request_spike`
- Severity: P3
- SLI/SLO liên quan: `daily_cost_usd`, ngân sách 2.5 USD.
- Điều kiện và thời gian duy trì: `sum(cost_usd)` theo phút vượt 2× giá trị trung vị 1 giờ, **duy trì 15 phút**, và **trong khi** traffic không tăng quá 20%. Điều kiện kép là điểm mấu chốt: chi phí tăng vì đông người dùng là chuyện bình thường, còn chi phí tăng khi traffic đứng yên nghĩa là chi phí *trên mỗi request* đã tăng — đó mới là hồi quy.
- Ảnh hưởng tới người dùng: không trực tiếp; đây là alert bảo vệ ngân sách nên để P3 và gửi vào ticket queue, không page ai lúc nửa đêm.
- Ba bước kiểm tra đầu tiên:
  1. So panel **Cost over time** với panel **Request traffic**. Hai đường tách nhau xác nhận là hồi quy đơn giá.
  2. Mở panel **Input and output tokens**: `tokens_out` tăng trong khi `tokens_in` đứng yên nghĩa là model sinh dài hơn, thường do đổi prompt hoặc thiếu giới hạn độ dài.
  3. Đối chiếu thời điểm tăng với `prompt_version` / `prompt_label` trên trace — nếu trùng lúc đổi label thì rollback prompt là hành động đầu tiên.
- Mitigation tạm thời: rollback prompt label về version trước, hoặc siết `max_tokens`.
- Owner: Đạt

## Vì sao không đặt alert cho quality proxy

`quality_score` là heuristic tính trong [`app/agent.py`](../app/agent.py) từ độ dài câu trả lời và mức trùng từ khoá, không phải phán quyết của con người về chất lượng. Nó đủ tốt để **quan sát xu hướng** trên dashboard nhưng quá nhiễu để đánh thức người trực. Nhóm theo dõi nó dưới dạng weekly review; chỉ khi có nhãn chất lượng thật (đánh giá người dùng hoặc LLM-as-judge đã hiệu chuẩn) mới nên gắn alert.

## Nguyên tắc chung của nhóm

- Alert theo **triệu chứng người dùng cảm nhận được**, không theo tên hàm nội bộ. `rag_slow` là nguyên nhân, `latency_p95_breach` mới là triệu chứng — alert đặt theo nguyên nhân sẽ bỏ sót mọi nguyên nhân khác gây cùng triệu chứng.
- Alert nào cũng phải có **duration**. Không có duration thì mỗi gai nhọn tức thời đều thành page và người trực sẽ học cách phớt lờ.
- Mỗi alert có đúng một owner và một runbook link. Alert không có bước xử lý cụ thể chỉ là tiếng ồn.
