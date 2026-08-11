from __future__ import annotations

import time
import uuid

import re

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from structlog.contextvars import bind_contextvars, clear_contextvars

# Chỉ nhận lại ID do upstream gửi khi nó đúng định dạng an toàn; ID lạ có thể
# chứa ký tự điều khiển và làm hỏng dòng log hoặc response header.
INBOUND_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


def new_correlation_id() -> str:
    return f"req-{uuid.uuid4().hex[:8]}"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Contextvars sống theo task; xoá đầu request để metadata của request
        # trước không rò sang request sau khi worker được tái sử dụng.
        clear_contextvars()

        inbound = (request.headers.get("x-request-id") or "").strip()
        correlation_id = inbound if INBOUND_ID_PATTERN.match(inbound) else new_correlation_id()

        bind_contextvars(correlation_id=correlation_id)

        request.state.correlation_id = correlation_id

        start = time.perf_counter()
        response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        response.headers["x-request-id"] = correlation_id
        response.headers["x-response-time-ms"] = f"{elapsed_ms:.1f}"

        return response
