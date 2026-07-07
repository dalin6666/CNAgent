from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any


class TelemetryRecorder:
    def __init__(self, log_dir: str, session_id: str) -> None:
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.log_dir / f"{session_id}.jsonl"

    def emit(self, event: str, **payload: Any) -> None:
        record = {
            "event": event,
            "ts_ms": int(time.time() * 1000),
            "payload": payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")

    @contextmanager
    def span(self, event: str, **payload: Any):
        start = time.perf_counter()
        self.emit(f"{event}.start", **payload)
        try:
            yield
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            self.emit(f"{event}.end", duration_ms=duration_ms, **payload)
