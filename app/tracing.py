from __future__ import annotations

import os
from typing import Any

try:
    from langfuse import get_client, observe

    LANGFUSE_SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - chỉ dùng khi chưa cài requirements
    LANGFUSE_SDK_AVAILABLE = False

    def observe(*args: Any, **kwargs: Any):
        def decorator(func):
            return func

        return decorator

    class _DummyClient:
        def update_current_trace(self, **kwargs: Any) -> None:
            return None

        def update_current_generation(self, **kwargs: Any) -> None:
            return None

        def flush(self) -> None:
            return None

    def get_client():
        return _DummyClient()


def get_langfuse_client():
    return get_client()


def flush_tracing() -> None:
    """Đẩy nốt batch trace còn trong buffer trước khi process thoát.

    SDK gom trace theo batch và gửi nền. Nếu process dừng ngay sau một request
    thì batch cuối chưa kịp gửi và trace mất luôn — mỗi lần restart hoặc deploy
    sẽ tạo một khoảng mù đúng vào lúc dễ xảy ra sự cố nhất.
    """
    if not LANGFUSE_SDK_AVAILABLE:
        return
    try:
        get_client().flush()
    except Exception:  # Không được để lỗi telemetry chặn shutdown của app.
        pass


def tracing_enabled() -> bool:
    return LANGFUSE_SDK_AVAILABLE and bool(
        os.getenv("LANGFUSE_PUBLIC_KEY") and os.getenv("LANGFUSE_SECRET_KEY")
    )
