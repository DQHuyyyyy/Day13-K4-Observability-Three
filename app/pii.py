from __future__ import annotations

import hashlib
import re

# Thứ tự quan trọng: pattern dài/cụ thể chạy trước để không bị pattern ngắn
# ăn mất một phần chuỗi rồi làm hỏng phần còn lại.
PII_PATTERNS: dict[str, str] = {
    "credit_card": r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b",
    "email": r"[\w\.-]+@[\w\.-]+\.\w+",
    "phone_vn": r"(?<!\d)(?:\+84|0)(?:[ .-]?\d){9}(?!\d)",
    "cccd": r"\b\d{12}\b",
    # Hộ chiếu VN: 1 chữ cái in hoa + 7 chữ số (ví dụ B1234567, C0123456).
    "passport_vn": r"\b[A-Z]\d{7}\b",
    # Địa chỉ VN: bắt theo từ khoá hành chính rồi nuốt tối đa 4 token phía sau.
    "address_vn": (
        r"(?i)\b(?:số nhà|đường|phố|phường|quận|huyện|thị trấn|thị xã|xã|ngõ|ngách|hẻm|tổ|ấp|thôn)"
        r"\s+[\wÀ-ỹ][\wÀ-ỹ./-]*(?:\s+[\wÀ-ỹ][\wÀ-ỹ./-]*){0,3}"
    ),
    # Số tài khoản ngân hàng khi đi kèm từ khoá, tránh quét mù mọi dãy số.
    "bank_account": r"(?i)\b(?:stk|số tài khoản|account(?: number)?)\s*[:#]?\s*\d{8,16}\b",
}

COMPILED_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(pattern) for name, pattern in PII_PATTERNS.items()
}


def scrub_text(text: str) -> str:
    safe = text
    for name, pattern in COMPILED_PII_PATTERNS.items():
        safe = pattern.sub(f"[REDACTED_{name.upper()}]", safe)
    return safe


def summarize_text(text: str, max_len: int = 80) -> str:
    safe = scrub_text(text).strip().replace("\n", " ")
    return safe[:max_len] + ("..." if len(safe) > max_len else "")


def hash_user_id(user_id: str) -> str:
    # Prefix "uh_" giữ hash luôn khác một dãy 12 chữ số thuần, nếu không một
    # digest toàn số sẽ bị chính detector CCCD báo nhầm là PII leak.
    return "uh_" + hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:12]
