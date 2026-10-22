"""测试辅助：临时目录、内存上下文、可复用的假阶段。"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from docforge import ArtifactStore, EventLog, RunContext, RunOptions  # noqa: E402
from docforge.stage import Stage, StageResult  # noqa: E402

EXAMPLES = ROOT / "examples" / "sample_pkg"


def tempdir(prefix: str = "case-") -> Path:
    """在项目下建临时目录（不用 tempfile：建出来的目录在某些环境写不进去）。"""
    base = ROOT / ".tests-tmp"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{prefix}{uuid.uuid4().hex[:10]}"
    path.mkdir()
    return path


def make_context(tmp: Path, *, source: Path | None = None, max_patch_rounds: int = 2,
                 start_stage: str | None = None, threads: int = 3) -> RunContext:
    options = RunOptions(
        source=source or EXAMPLES,
        out_dir=tmp / "out",
        max_patch_rounds=max_patch_rounds,
        threads=threads,
        start_stage=start_stage,
    )
    store = ArtifactStore(dump_dir=tmp / "artifacts")
    log = EventLog(jsonl_path=tmp / "events.jsonl")
    return RunContext(options=options, store=store, log=log)


class Trace(Stage):
    """把执行顺序记进工件 trail，用来断言流程走向。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.title = f"{name} 阶段"

    def run(self, ctx: RunContext) -> StageResult:
        trail = list(ctx.optional("trail", []) or [])
        trail.append(self.name)
        return StageResult(artifacts={"trail": trail}, message=f"{self.name} 完成")


class FlagSetter(Stage):
    """把一个开关工件置为指定值（用来模拟"补写后不再需要补写"）。"""

    def __init__(self, name: str, flag: str, value) -> None:
        self.name = name
        self.title = f"{name} 阶段"
        self.flag = flag
        self.value = value

    def run(self, ctx: RunContext) -> StageResult:
        return StageResult(artifacts={self.flag: self.value}, message=f"{self.flag} → {self.value}")


class FlagOnce(Stage):
    """只在第一次执行时设置开关，之后保持不动（模拟"校验只在首轮报缺口"）。"""

    def __init__(self, name: str, flag: str, value) -> None:
        self.name = name
        self.title = f"{name} 阶段"
        self.flag = flag
        self.value = value

    def run(self, ctx: RunContext) -> StageResult:
        if ctx.has(self.flag):
            return StageResult(message=f"{self.flag} 保持不变")
        return StageResult(artifacts={self.flag: self.value}, message=f"{self.flag} → {self.value}")


class Flaky(Stage):
    """前 N 次抛异常，之后成功。"""

    def __init__(self, name: str, fail_times: int = 1) -> None:
        self.name = name
        self.title = f"{name} 阶段"
        self.fail_times = fail_times
        self.calls = 0

    def run(self, ctx: RunContext) -> StageResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError(f"{self.name} 第 {self.calls} 次故意失败")
        return StageResult(artifacts={"flaky": self.calls}, message=f"{self.name} 成功（第 {self.calls} 次）")


class Broken(Stage):
    """永远失败。"""

    def __init__(self, name: str = "broken") -> None:
        self.name = name
        self.title = "故障阶段"

    def run(self, ctx: RunContext) -> StageResult:
        raise RuntimeError("阶段炸了")
