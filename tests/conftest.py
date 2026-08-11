from __future__ import annotations

import pytest

from app import logging_config


@pytest.fixture(autouse=True)
def isolate_log_file(tmp_path, monkeypatch):
    """Giữ test tách khỏi `data/logs.jsonl`.

    File đó là evidence nộp bài: nếu test ghi thêm event vào, số liệu trong
    `validate_logs.py` sẽ lẫn dữ liệu không đến từ request thật.
    """
    monkeypatch.setattr(logging_config, "LOG_PATH", tmp_path / "logs.jsonl")
