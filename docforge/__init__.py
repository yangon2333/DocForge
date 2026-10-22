"""DocForge —— 代码文档生成工作流。

设计骨架：
    Artifact（工件）  带版本号的数据单元，是阶段之间唯一的传递物
    ArtifactStore     工件仓库：版本管理 + 落盘，支撑 --from 重跑
    EventLog          事件流：阶段广播 + JSONL 落盘 + 终端渲染
    RunContext        运行上下文：仓库、事件、选项、信箱、计数
    Stage             阶段（作业里的 "Agent"）：一个可独立测试的处理单元
    Pipeline          流水线：顺序 / 条件回边 / 轮次守卫 / 并行批处理

对外入口见 run.py，设计取舍见 DESIGN.md。
"""

from __future__ import annotations

__version__ = "1.0.0"
__author__ = "2323040304 张子炀"

from .artifact import Artifact, ArtifactStore, MissingArtifact
from .context import RunContext, RunOptions
from .events import Event, EventLog
from .pipeline import BranchStep, Pipeline, PipelineError, StageStep
from .stage import ParallelStage, Stage, StageError, StageResult

__all__ = [
    "Artifact",
    "ArtifactStore",
    "BranchStep",
    "Event",
    "EventLog",
    "MissingArtifact",
    "ParallelStage",
    "Pipeline",
    "PipelineError",
    "RunContext",
    "RunOptions",
    "Stage",
    "StageError",
    "StageResult",
    "StageStep",
]
