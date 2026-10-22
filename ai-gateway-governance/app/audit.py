from __future__ import annotations

from collections import deque
import json
import logging
from pathlib import Path
import threading
from typing import Any


logger = logging.getLogger("ai_gateway_demo.audit")


class AuditTrail:
    """Keeps recent audit events in memory and appends every event to a JSONL file."""

    def __init__(self, path: str | None, capacity: int = 300) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._lock = threading.Lock()
        self._path = Path(path) if path else None
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        line = json.dumps(event, ensure_ascii=False, default=str)
        with self._lock:
            self._events.append(event)
            if self._path:
                with self._path.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
        logger.info(
            "audit id=%s run=%s path=%s requested=%s served=%s status=%s decision=%s",
            event.get("id"),
            event.get("runId"),
            event.get("path"),
            event.get("requestedModel"),
            event.get("servedModel"),
            event.get("httpStatus"),
            event.get("gatewayDecision"),
        )
        return event

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events)[-limit:][::-1]

    def get(self, event_id: str) -> dict[str, Any] | None:
        with self._lock:
            return next((e for e in self._events if e.get("id") == event_id), None)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()
