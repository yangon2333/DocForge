"""工件与工件仓库。

工件是本项目里阶段之间唯一的传递物：阶段不调用别的阶段，也不直接读写全局变量，
只从仓库里取上游工件、再把自己的产出放回仓库。好处是每个阶段都能单独重跑。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


class MissingArtifact(LookupError):
    """仓库里没有这个工件（通常说明上游阶段没跑或跑失败了）。"""


@dataclass
class Artifact:
    """一个带版本号的工件。"""

    name: str
    payload: Any
    creator: str
    version: int = 1
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "creator": self.creator,
            "version": self.version,
            "created_at": round(self.created_at, 4),
            "payload": self.payload,
        }

    def brief(self, limit: int = 90) -> str:
        """给日志用的一行摘要，避免把整份源码打进控制台。"""
        if isinstance(self.payload, dict):
            keys = ", ".join(sorted(self.payload)[:6])
            text = f"{self.name} v{self.version} {{{keys}}}"
        elif isinstance(self.payload, list):
            text = f"{self.name} v{self.version} [list ×{len(self.payload)}]"
        else:
            text = f"{self.name} v{self.version} {type(self.payload).__name__}"
        return text[:limit]


class ArtifactStore:
    """内存 + 磁盘两层的工件仓库。"""

    def __init__(self, dump_dir: Path | None = None) -> None:
        self._items: dict[str, Artifact] = {}
        self._history: dict[str, list[Artifact]] = {}
        self._dump_dir = Path(dump_dir) if dump_dir else None

    # ---------------------------------------------------------------- 写
    def put(self, name: str, payload: Any, *, creator: str) -> Artifact:
        version = self._items[name].version + 1 if name in self._items else 1
        artifact = Artifact(name=name, payload=payload, creator=creator, version=version)
        self._items[name] = artifact
        self._history.setdefault(name, []).append(artifact)
        if self._dump_dir:
            self._dump(artifact)
        return artifact

    # ---------------------------------------------------------------- 读
    def get(self, name: str) -> Artifact:
        try:
            return self._items[name]
        except KeyError:
            raise MissingArtifact(f"缺少工件 {name!r}；已有：{sorted(self._items)}") from None

    def payload(self, name: str) -> Any:
        return self.get(name).payload

    def maybe(self, name: str, default: Any = None) -> Any:
        artifact = self._items.get(name)
        return artifact.payload if artifact else default

    def has(self, name: str) -> bool:
        return name in self._items

    def keys(self) -> list[str]:
        return sorted(self._items)

    def with_prefix(self, prefix: str) -> list[Artifact]:
        return [self._items[key] for key in self.keys() if key.startswith(prefix)]

    def versions(self, name: str) -> list[int]:
        return [item.version for item in self._history.get(name, [])]

    def __len__(self) -> int:
        return len(self._items)

    # ---------------------------------------------------------------- 落盘
    def _dump(self, artifact: Artifact) -> None:
        assert self._dump_dir is not None
        self._dump_dir.mkdir(parents=True, exist_ok=True)
        safe = artifact.name.replace(":", "__").replace("/", "_").replace("\\", "_")
        path = self._dump_dir / f"{safe}.v{artifact.version}.json"
        path.write_text(
            json.dumps(artifact.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def dump_summary(self) -> dict[str, int]:
        return {key: item.version for key, item in sorted(self._items.items())}

    @classmethod
    def load(cls, dump_dir: Path) -> "ArtifactStore":
        """从磁盘恢复最新版本工件（--from 重跑时用）。"""
        store = cls(dump_dir=None)
        folder = Path(dump_dir)
        if not folder.is_dir():
            return store
        newest: dict[str, tuple[int, Path]] = {}
        for path in folder.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            name = data.get("name")
            version = int(data.get("version", 0))
            if not name:
                continue
            if name not in newest or version > newest[name][0]:
                newest[name] = (version, path)
        for name, (version, path) in newest.items():
            data = json.loads(path.read_text(encoding="utf-8"))
            artifact = Artifact(
                name=name,
                payload=data.get("payload"),
                creator=data.get("creator", "restored"),
                version=version,
                created_at=float(data.get("created_at", time.time())),
            )
            store._items[name] = artifact
            store._history.setdefault(name, []).append(artifact)
        return store

    def filter(self, predicate) -> Iterable[Artifact]:
        return (self._items[key] for key in self.keys() if predicate(self._items[key]))
