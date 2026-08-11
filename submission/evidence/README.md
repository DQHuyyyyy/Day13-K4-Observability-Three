# Evidence — danh sách và cách thu thập

Thư mục này chứa bằng chứng nộp kèm [`../REPORT.md`](../REPORT.md).
File `.txt` và `.json` đã sinh tự động từ log thật. Phần còn lại là **ảnh phải chụp tay**
vì nằm ngoài repo (Langfuse UI) hoặc cần render trong trình duyệt.

Đặt tên đúng như bảng dưới. Báo cáo đã dẫn theo những tên này, sai tên là link gãy.

**Trạng thái: đủ evidence.** 7 ảnh và 9 file dữ liệu đã có mặt.

## Đã có sẵn (không cần làm gì)

| File | Nội dung | Sinh bằng |
|---|---|---|
| `validate_logs_baseline.txt` | 30/100 ở commit gốc | `git worktree` + `scripts/validate_logs.py` |
| `validate_logs_final.txt` | 100/100, 144 record, 39 correlation ID, 0 PII leak | `python scripts/validate_logs.py` |
| `validate_dashboard.txt` | `HỢP LỆ: 6/6 panel` | `python scripts/validate_dashboard.py` |
| `log_correlation_id.json` | 4 log record đủ correlation ID và enrichment | trích từ `data/logs.jsonl` |
| `log_pii_redacted.json` | email / phone / thẻ đã thành `[REDACTED_*]` | trích từ `data/logs.jsonl` |
| `log_request_failed.json` | log lỗi làm error rate chạm 2.86% | trích từ `data/logs.jsonl` |
| `challenge_investigation.txt` | phân rã latency theo span, percentile 3 pha | trích từ `data/logs.jsonl` |
| `prompt_versioning.txt` | 4 trace ID kèm label/version/source | Langfuse API |
| `dashboard.html` | 6 panel đã dựng | `python scripts/build_dashboard.py` |
| `dashboard.png` | Ảnh chụp 6 panel — **đã có** | chụp màn hình `dashboard.html` |

## Ảnh phải chụp

Project Langfuse: `My Project` — id `cmsodnmx902biad0kxd93otav`
Link theo mẫu `https://cloud.langfuse.com/project/cmsodnmx902biad0kxd93otav/...`
(nếu link không mở được thì tự điều hướng trong UI, id project vẫn đúng).

### Duy — xong

`dashboard.png` đã chụp: đủ 6 panel trong một ảnh, đọc được tên panel, `time range 60 phút`,
khoảng `08:36 → 08:54`, `refresh 30s`, nguồn `data/logs.jsonl`, đơn vị và threshold từng panel,
kèm chip đạt/vi phạm. Muốn dựng lại sau khi có log mới thì chạy
`python scripts/build_dashboard.py` rồi chụp lại.

### Đạt — 6 ảnh, đã xong

Bảng dưới giữ lại cách chụp để dựng lại được nếu cần.

| Tên file | Chụp gì | Cách chụp |
|---|---|---|
| `trace_list.png` | Danh sách traces, **≥ 10 dòng** | Vào **Tracing**. Langfuse v4 gộp trace và observation vào một bảng, nên phải đặt filter `Is Root Observation = True` để mỗi trace còn một dòng — kiểm chứng bằng `Total ≈ 69` ở góc dưới. Bấm `Columns`, tắt `Input`/`Output` (rỗng vì `capture_input=False`) và bật `Metadata`. Chụp kèm dòng `Total`. |
| `trace_waterfall.png` | Waterfall đầy đủ của một trace | Mở trace `76b1fe4d75a4364c7575064c575b4974`. Phải thấy span cha và span generation con, kèm thanh thời lượng. |
| `trace_prompt_metadata.png` | Metadata gắn prompt vào trace | Vẫn ở trace trên, mở tab **Metadata**. Phải đọc được `prompt_name`, `prompt_label`, `prompt_version`, `prompt_source=langfuse`. Đây là ảnh chứng minh trace liên kết đúng phiên bản prompt. |
| `prompt_version1.png` | Version 1 của `day13-chat` | **Prompt Management → Prompts → day13-chat**, chọn `#1`. Thấy label `production` + `baseline` và nội dung prompt. |
| `prompt_version2.png` | Version 2 | Chọn `#2`. Thấy label `latest` + `candidate` và dòng `Answer in at most 3 sentences...` mà v1 không có. |
| `prompt_rollback.png` | Label `production` nằm ở **version 2** | Gắn `production` lên v2 rồi chụp. Đây là trạng thái "trước rollback"; `prompt_version1.png` chính là trạng thái "sau rollback" khi `production` đã về v1. Hai ảnh ghép lại là bằng chứng đổi label. |

**Cảnh báo khi đổi label trên UI.** Langfuse **thay toàn bộ** tập label của một
version chứ không cộng thêm. Tick `production` cho v2 sẽ kéo theo các label khác
và làm mất `baseline` / `candidate`. Trạng thái đúng phải là:

| Version | Label |
|---|---|
| 1 | `production`, `baseline` |
| 2 | `candidate`, `latest` *(`latest` do Langfuse tự quản lý)* |

Kiểm tra lại bất cứ lúc nào:

```python
from langfuse import get_client
c = get_client()
for v in (1, 2):
    print(v, c.api.prompts.get("day13-chat", version=v).labels)
```

### Huy — 1 ảnh (khuyến khích, không bắt buộc)

| Tên file | Chụp gì | Cách chụp |
|---|---|---|
| `validate_logs_terminal.png` | Kết quả validator trên terminal | Chạy `python scripts/validate_logs.py`, chụp cả 4 dòng `[PASSED]` và dòng `Estimated Score: 100/100`. |

Bằng chứng logging/PII đã đủ ở dạng file JSON nên ảnh này chỉ để demo cho trực quan.

## Quy ước chung

- Định dạng `.png`, không đặt tên có dấu cách hoặc dấu tiếng Việt.
- Không che, không cắt ghép, không chỉnh sửa nội dung ảnh — `RULES.md` cấm làm giả evidence.
- **Che key nếu lỡ lọt vào khung hình.** Langfuse UI không hiện secret key ở các trang trên, nhưng nếu chụp nhầm trang Settings thì phải che `sk-lf-...`.
- Sau khi chụp xong, kiểm tra lại đường dẫn trong báo cáo:

  ```bash
  grep -o "evidence/[a-z0-9_.-]*" submission/REPORT.md | sort -u
  ```
