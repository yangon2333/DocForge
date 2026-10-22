"""analyze：并行解析每个模块的 AST 结构。

这个阶段是"批处理"：一个模块一个任务，用线程池并行跑。
好处的 4 个模块和 400 个模块代码一样，只是线程数封顶。
"""

from __future__ import annotations

from pathlib import Path

from ..astlib import parse_source
from ..context import RunContext
from ..stage import ParallelStage


class AnalyzeStage(ParallelStage):
    name = "analyze"
    title = "解析模块结构"
    items_key = "scan"
    prefix = "module:"

    def item_id(self, item: dict) -> str:
        return str(item["module"])

    def run_one(self, ctx: RunContext, item: dict) -> dict:
        root = Path(ctx.require("scan")["root"])
        info = parse_source(item["source"], path=item["abs"], root=root.parent)
        data = info.to_dict()
        # 用 scan 阶段算好的名字与相对路径，保证文档里的链接一致
        data["module"] = item["module"]
        data["path"] = item["path"]
        return data

    def run(self, ctx: RunContext):
        result = super().run(ctx)
        parsed = [name for name in result.artifacts if name.startswith(self.prefix)]
        ctx.log.emit(
            "detail",
            f"{len(parsed)} 个模块解析完成，产物：{', '.join(sorted(parsed)[:6])}"
            + ("…" if len(parsed) > 6 else ""),
            stage=self.name,
        )
        return result
