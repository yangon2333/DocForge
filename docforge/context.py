"""运行上下文：一次运行的可变状态都挂在这里，阶段通过它取工件、记事件、收发便条。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .artifact import ArtifactStore
from .events import EventLog


@dataclass
class RunOptions:
    source: Path
    out_dir: Path
    max_patch_rounds: int = 2
    threads: int = 4
    start_stage: str | None = None
    quiet: bool = False
    student: str = "2323040304 张子炀"
    complexity_limit: int = 8


class RunContext:
    """阶段之间唯一的共享入口。"""

    def __init__(self, options: RunOptions, store: ArtifactStore, log: EventLog) -> None:
        self.options = options
        self.store = store
        self.log = log
        self.rounds = 0
        self.guard_hits = 0
        self.stage_times: dict[str, float] = {}
        self.notes: list[str] = []
        self._mail: dict[str, list[dict[str, str]]] = {}

    # ---------------------------------------------------------------- 工件
    def require(self, name: str) -> Any:
        return self.store.payload(name)

    def optional(self, name: str, default: Any = None) -> Any:
        return self.store.maybe(name, default)

    def has(self, name: str) -> bool:
        return self.store.has(name)

    def put(self, name: str, payload: Any, *, creator: str) -> None:
        self.store.put(name, payload, creator=creator)

    # ---------------------------------------------------------------- 便条（点对点消息）
    def post(self, to: str, text: str, *, sender: str) -> None:
        """给某个下游阶段留一条便条。用于传递"工件里放不下的判断"。"""
        self._mail.setdefault(to, []).append({"from": sender, "text": text})

    def inbox(self, stage: str) -> list[dict[str, str]]:
        return list(self._mail.get(stage, []))

    def take_mail(self, stage: str) -> list[dict[str, str]]:
        return self._mail.pop(stage, [])

    # ---------------------------------------------------------------- 杂项
    def note(self, text: str) -> None:
        self.notes.append(text)

    def summary(self) -> dict[str, Any]:
        return {
            "rounds": self.rounds,
            "guard_hits": self.guard_hits,
            "artifacts": len(self.store),
            "stages": {key: round(value, 4) for key, value in self.stage_times.items()},
        }
