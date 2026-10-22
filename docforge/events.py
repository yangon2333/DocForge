"""事件流：阶段把"我在干什么"广播出来，终端和 JSONL 都只是订阅者。

和"工件"的分工：
    工件   —— 内容（数据本身），下游要读它才能干活
    事件   —— 过程（发生了什么），只用于观测，丢了也不影响正确性
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

Sink = Callable[["Event"], None]


@dataclass
class Event:
    kind: str
    message: str
    stage: str = ""
    elapsed: float = 0.0
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ts": round(self.ts, 4),
            "kind": self.kind,
            "stage": self.stage,
            "elapsed": round(self.elapsed, 4),
            "message": self.message,
            "data": self.data,
        }


class EventLog:
    def __init__(self, jsonl_path: Path | None = None) -> None:
        self._events: list[Event] = []
        self._sinks: list[Sink] = []
        self._jsonl = Path(jsonl_path) if jsonl_path else None
        self._t0 = time.perf_counter()
        if self._jsonl:
            self._jsonl.parent.mkdir(parents=True, exist_ok=True)
            self._jsonl.write_text("", encoding="utf-8")

    # ---------------------------------------------------------------- 订阅
    def subscribe(self, sink: Sink) -> None:
        self._sinks.append(sink)

    # ---------------------------------------------------------------- 发事件
    def emit(
        self,
        kind: str,
        message: str = "",
        *,
        stage: str = "",
        elapsed: float = 0.0,
        **data: Any,
    ) -> Event:
        event = Event(kind=kind, message=message, stage=stage, elapsed=elapsed, data=data)
        self._events.append(event)
        if self._jsonl:
            with self._jsonl.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        for sink in self._sinks:
            try:
                sink(event)
            except Exception:  # 展示层出错不能影响流程
                pass
        return event

    # ---------------------------------------------------------------- 查询
    @property
    def events(self) -> list[Event]:
        return list(self._events)

    def kinds(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for event in self._events:
            counts[event.kind] = counts.get(event.kind, 0) + 1
        return counts

    def elapsed(self) -> float:
        return time.perf_counter() - self._t0

    def warnings(self) -> list[Event]:
        return [event for event in self._events if event.kind in ("warn", "guard", "retry")]
