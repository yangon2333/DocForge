"""各阶段实现 + 默认流程装配。

流程全貌就在 build_pipeline() 这十几行里：
    扫描 → 解析（并行）→ 汇总 → 渲染 → 校验 ─┬─ 通过 ─→ 落盘
                                          └─ 有缺口 → 补写 ─→ 回到渲染（最多 N 轮）
"""

from __future__ import annotations

from ..context import RunContext, RunOptions
from ..pipeline import Pipeline
from .analyze import AnalyzeStage
from .assemble import AssembleStage
from .catalog import CatalogStage
from .repair import RepairStage
from .scan import ScanStage
from .validate import ValidateStage
from .write import WriteStage

__all__ = [
    "AnalyzeStage",
    "AssembleStage",
    "CatalogStage",
    "RepairStage",
    "ScanStage",
    "ValidateStage",
    "WriteStage",
    "build_pipeline",
    "needs_repair",
]


def needs_repair(ctx: RunContext) -> bool:
    """校验阶段报出的阻断级缺口是否还需要补写。"""
    data = ctx.require("gaps")
    return int(data.get("blocking", 0)) > 0


def build_pipeline(options: RunOptions) -> Pipeline:
    pipeline = Pipeline("docgen", "代码 → 分析 → 文档")
    pipeline.add(ScanStage())
    pipeline.add(AnalyzeStage(), parallel=True)
    pipeline.add(CatalogStage())
    pipeline.add(WriteStage())
    pipeline.add(ValidateStage())
    pipeline.branch(
        name="decide_repair",
        title="覆盖率不足 → 补写并重新渲染",
        test=needs_repair,
        stage=RepairStage(),
        goto="write",
        max_rounds=options.max_patch_rounds,
        otherwise="assemble",
    )
    pipeline.add(AssembleStage())
    return pipeline
