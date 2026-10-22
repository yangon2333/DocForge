"""流水线：用**代码**表达流程控制（顺序 / 条件回边 / 轮次守卫）。

为什么不用 JSON 配置流程：本项目的流程里有两个"回边 + 计数"的判断，
写成 Python 函数更直白、可被类型检查和单元测试覆盖；流程本身就在
build_pipeline() 里，读那一份代码就知道全貌。
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

from .artifact import MissingArtifact
from .context import RunContext
from .stage import Stage


class PipelineError(RuntimeError):
    """阶段失败或流程定义不合法。"""


@dataclass
class StepOutcome:
    """一步跑完后的去向：None 表示顺延到下一步。"""

    next_name: str | None = None


class Step(ABC):
    def __init__(self, name: str, title: str, *, on_fail: str = "abort", retries: int = 0) -> None:
        if on_fail not in ("abort", "skip"):
            raise ValueError(f"on_fail 只能是 abort / skip，收到 {on_fail!r}")
        self.name = name
        self.title = title
        self.on_fail = on_fail
        self.retries = max(0, retries)
        self.last_message = ""

    @abstractmethod
    def run(self, ctx: RunContext) -> StepOutcome:
        ...

    @property
    def kind(self) -> str:
        return "stage"


class StageStep(Step):
    """执行一个阶段。"""

    def __init__(
        self,
        stage: Stage,
        *,
        name: str | None = None,
        title: str | None = None,
        on_fail: str = "abort",
        retries: int = 0,
    ) -> None:
        super().__init__(name or stage.name, title or stage.title, on_fail=on_fail, retries=retries)
        self.stage = stage
        self.parallel = False

    def run(self, ctx: RunContext) -> StepOutcome:
        attempts = self.retries + 1
        last: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                result = self.stage.execute(ctx)
                self.last_message = result.message
                return StepOutcome()
            except MissingArtifact:
                raise  # 缺上游工件是流程问题，重试没意义
            except Exception as exc:  # noqa: BLE001 - 阶段失败按策略处理
                last = exc
                if attempt < attempts:
                    ctx.log.emit(
                        "retry",
                        f"第 {attempt} 次失败，准备重试：{exc}",
                        stage=self.name,
                        attempt=attempt,
                    )
        assert last is not None
        if self.on_fail == "skip":
            ctx.log.emit("warn", f"阶段失败已跳过：{last}", stage=self.name, error=str(last))
            self.last_message = f"失败已跳过（{type(last).__name__}）"
            return StepOutcome()
        raise PipelineError(f"阶段 {self.name} 失败：{type(last).__name__}: {last}") from last


class BranchStep(Step):
    """条件分支 + 回边（循环）。

    test 成立时执行 stage，然后跳回 goto 指定的阶段；连续成立超过
    max_rounds 次就放弃回边、直接走 otherwise（这就是循环守卫）。
    """

    kind = "branch"

    def __init__(
        self,
        *,
        name: str,
        title: str,
        test: Callable[[RunContext], bool],
        stage: Stage,
        goto: str,
        max_rounds: int = 2,
        otherwise: str | None = None,
        retries: int = 0,
    ) -> None:
        super().__init__(name, title, retries=retries)
        self.test = test
        self.stage = stage
        self.goto = goto
        self.max_rounds = max(0, max_rounds)
        self.otherwise = otherwise
        self.rounds_used = 0

    def run(self, ctx: RunContext) -> StepOutcome:
        fire = bool(self.test(ctx))
        if fire and self.rounds_used < self.max_rounds:
            self.rounds_used += 1
            ctx.rounds += 1
            result = self.stage.execute(ctx)
            self.last_message = (
                f"条件成立 → {self.stage.title}（第 {self.rounds_used}/{self.max_rounds} 轮）"
                f"，回边到 {self.goto}"
            )
            ctx.log.emit(
                "branch",
                self.last_message + (f"：{result.message}" if result.message else ""),
                stage=self.name,
                round=self.rounds_used,
                goto=self.goto,
            )
            return StepOutcome(next_name=self.goto)

        if fire:
            ctx.guard_hits += 1
            self.last_message = f"补写已达 {self.max_rounds} 轮上限，跳过回边直接收尾"
            ctx.log.emit("guard", self.last_message, stage=self.name, limit=self.max_rounds)
        else:
            self.last_message = "条件不成立，直接进入下一阶段"
            ctx.log.emit("branch", self.last_message, stage=self.name, goto=self.otherwise or "next")
        return StepOutcome(next_name=self.otherwise)


@dataclass
class RunSummary:
    pipeline: str
    status: str
    stages_run: int
    rounds: int
    guard_hits: int
    duration: float
    artifacts: dict[str, int] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.status == "completed"


class Pipeline:
    """阶段的有序集合 + 控制流。"""

    def __init__(self, name: str, description: str = "") -> None:
        self.name = name
        self.description = description
        self.steps: list[Step] = []

    # ---------------------------------------------------------------- 组装
    def add(
        self,
        stage: Stage,
        *,
        name: str | None = None,
        title: str | None = None,
        on_fail: str = "abort",
        retries: int = 0,
        parallel: bool = False,
    ) -> "Pipeline":
        step = StageStep(stage, name=name, title=title, on_fail=on_fail, retries=retries)
        step.parallel = parallel
        self.steps.append(step)
        return self

    def branch(
        self,
        *,
        name: str,
        title: str,
        test: Callable[[RunContext], bool],
        stage: Stage,
        goto: str,
        max_rounds: int = 2,
        otherwise: str | None = None,
    ) -> "Pipeline":
        self.steps.append(
            BranchStep(
                name=name,
                title=title,
                test=test,
                stage=stage,
                goto=goto,
                max_rounds=max_rounds,
                otherwise=otherwise,
            )
        )
        return self

    # ---------------------------------------------------------------- 校验
    def _index(self) -> dict[str, int]:
        index: dict[str, int] = {}
        for position, step in enumerate(self.steps):
            if step.name in index:
                raise PipelineError(f"阶段名重复：{step.name!r}")
            index[step.name] = position
        return index

    def compile(self) -> dict[str, int]:
        index = self._index()
        for step in self.steps:
            if isinstance(step, BranchStep):
                if step.goto not in index:
                    raise PipelineError(f"{step.name} 的回边目标 {step.goto!r} 不存在")
                if step.otherwise and step.otherwise not in index:
                    raise PipelineError(f"{step.name} 的 otherwise 目标 {step.otherwise!r} 不存在")
                if index[step.goto] > index[step.name]:
                    raise PipelineError(f"{step.name} 的回边必须指向更早的阶段")
        return index

    # ---------------------------------------------------------------- 执行
    def run(self, ctx: RunContext) -> RunSummary:
        index = self.compile()
        pc = 0
        if ctx.options.start_stage:
            stage_name = ctx.options.start_stage
            if stage_name not in index:
                raise PipelineError(
                    f"--from {stage_name!r} 不存在；可选：{list(index)}"
                )
            pc = index[stage_name]
            ctx.log.emit("resume", f"从阶段 {stage_name} 开始（复用已有工件）", stage=stage_name)

        started = time.perf_counter()
        status, error, executed = "completed", None, 0
        ctx.log.emit(
            "run_start",
            f"流水线 {self.name} 启动：{len(self.steps)} 个阶段，起点 {self.steps[pc].name}",
            stages=len(self.steps),
        )

        try:
            while 0 <= pc < len(self.steps):
                step = self.steps[pc]
                began = time.perf_counter()
                ctx.log.emit("stage_start", step.title, stage=step.name)
                try:
                    outcome = step.run(ctx)
                finally:
                    spent = time.perf_counter() - began
                    ctx.stage_times[step.name] = ctx.stage_times.get(step.name, 0.0) + spent
                executed += 1
                ctx.log.emit(
                    "stage_done",
                    step.last_message or "完成",
                    stage=step.name,
                    elapsed=spent,
                )
                pc = index[outcome.next_name] if outcome.next_name else pc + 1
        except PipelineError as exc:
            status, error = "failed", str(exc)
            ctx.log.emit("error", str(exc))
        except MissingArtifact as exc:
            status, error = "failed", f"缺少上游工件：{exc}"
            ctx.log.emit("error", error)

        duration = time.perf_counter() - started
        ctx.log.emit(
            "run_end",
            f"流水线结束：{status}，执行 {executed} 次阶段，补写 {ctx.rounds} 轮",
            status=status,
            duration=duration,
        )
        return RunSummary(
            pipeline=self.name,
            status=status,
            stages_run=executed,
            rounds=ctx.rounds,
            guard_hits=ctx.guard_hits,
            duration=duration,
            artifacts=ctx.store.dump_summary(),
            notes=list(ctx.notes),
            error=error,
        )

    # ---------------------------------------------------------------- 展示
    def ascii(self) -> str:
        index = self.compile()
        lines: list[str] = []
        label_width = max((len(step.name) for step in self.steps), default=4)
        for position, step in enumerate(self.steps, start=1):
            mark = ">>" if step.kind == "stage" else "??"
            extra = "  (批处理·并行)" if getattr(step, "parallel", False) else ""
            lines.append(f"  {position}. [{mark}] {step.name:<{label_width}}  {step.title}{extra}")
        back_edges = [
            f"{step.name} --回边--> {step.goto}（最多 {step.max_rounds} 轮）"
            for step in self.steps
            if isinstance(step, BranchStep)
        ]
        if back_edges:
            lines.append("")
            lines.append("  回边 / 循环：")
            for edge in back_edges:
                lines.append(f"    {edge}")
        return "\n".join(lines)
