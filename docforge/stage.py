"""阶段（Stage）—— 作业里说的 "Agent"。

一个阶段只做一件事，只依赖上下文里的工件，因此可以脱离流程单独测试。
两种写法：
    Stage         顺序执行（一次处理一份输入）
    ParallelStage 批处理：同一段逻辑并行作用在多个条目上（每个模块一个任务）
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .context import RunContext


class StageError(RuntimeError):
    """阶段内部的可预期失败（例如目标目录里没有 .py 文件）。"""


@dataclass
class StageResult:
    """阶段的产出：要放进仓库的工件 + 一行摘要 + 给下游的便条。"""

    artifacts: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    messages: list[tuple[str, str]] = field(default_factory=list)

    def say(self, to: str, text: str) -> "StageResult":
        self.messages.append((to, text))
        return self


class Stage(ABC):
    name: str = "stage"
    title: str = "阶段"

    @abstractmethod
    def run(self, ctx: RunContext) -> StageResult:
        """子类实现：读上下文、算结果、返回 StageResult。"""

    # ------------------------------------------------------------------ 模板方法
    def execute(self, ctx: RunContext) -> StageResult:
        """统一入口：把结果里的工件写进仓库、把便条投递出去。"""
        result = self.run(ctx)
        if not isinstance(result, StageResult):
            raise StageError(f"{self.name}.run() 必须返回 StageResult")
        for key, payload in result.artifacts.items():
            ctx.put(key, payload, creator=self.name)
        for to, text in result.messages:
            ctx.post(to, text, sender=self.name)
        return result

    def __repr__(self) -> str:  # pragma: no cover
        return f"<{type(self).__name__} name={self.name}>"


class ParallelStage(Stage):
    """把同一段处理逻辑并行作用在一批条目上。

    子类只需要实现 items() / item_id() / run_one()：
        items()    从上游工件里取出这批条目
        item_id()  每个条目的唯一标识（用来拼工件名）
        run_one()  处理单个条目（要求纯函数：不写 ctx、不发便条）
    """

    items_key: str = ""
    prefix: str = "item:"
    workers: int | None = None

    def items(self, ctx: RunContext) -> list[dict[str, Any]]:
        return list(ctx.require(self.items_key).get("files", []))

    def item_id(self, item: dict[str, Any]) -> str:
        return str(item.get("module") or item.get("path"))

    @abstractmethod
    def run_one(self, ctx: RunContext, item: dict[str, Any]) -> Any:
        """处理单个条目，返回要落进仓库的内容。"""

    def run(self, ctx: RunContext) -> StageResult:
        items = self.items(ctx)
        if not items:
            raise StageError(f"{self.name}：没有可处理的条目")

        workers = min(self.workers or ctx.options.threads, len(items))
        results: dict[str, Any] = {}
        failures: list[tuple[str, str]] = []

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            futures = {pool.submit(self.run_one, ctx, item): item for item in items}
            for future, item in futures.items():
                key = self.item_id(item)
                try:
                    results[key] = future.result()
                except Exception as exc:  # noqa: BLE001 - 单条失败不该拖垮整批
                    failures.append((key, f"{type(exc).__name__}: {exc}"))

        if not results:
            raise StageError(f"{self.name}：全部 {len(items)} 个条目都分析失败：{failures}")

        artifacts = {f"{self.prefix}{key}": value for key, value in results.items()}
        message = f"并行处理 {len(results)}/{len(items)} 个条目（{workers} 线程）"
        result = StageResult(artifacts=artifacts, message=message)
        if failures:
            result.artifacts[f"{self.prefix}failures"] = failures
            result.message += f"，失败 {len(failures)} 个"
        return result
