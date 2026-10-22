"""write：把模块事实渲染成 Markdown。

同一份事实渲染两次（补写前后）必须只有补写部分不同，所以这里没有任何随机性。
"""

from __future__ import annotations

import datetime as dt

from ..context import RunContext
from ..render import render_module, render_readme
from ..stage import Stage, StageResult


class WriteStage(Stage):
    name = "write"
    title = "生成 Markdown 章节"

    def run(self, ctx: RunContext) -> StageResult:
        catalog = ctx.require("catalog")
        modules = catalog["modules"]
        patched = ctx.optional("patched", {}) or {}
        round_no = ctx.rounds + 1
        generated_at = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        meta = {
            "student": ctx.options.student,
            "source": str(ctx.options.source),
            "complexity_limit": ctx.options.complexity_limit,
            "round": round_no,
        }

        pages = {
            module["module"]: render_module(module, patched, generated_at=generated_at)
            for module in modules
        }
        readme = render_readme(modules, meta=meta, patched=patched, generated_at=generated_at)

        letters = [item["text"] for item in ctx.take_mail(self.name)]
        result = StageResult(
            artifacts={
                "draft": {
                    "pages": pages,
                    "readme": readme,
                    "generated_at": generated_at,
                    "meta": meta,
                    "notes": letters,
                    "round": round_no,
                }
            },
            message=f"渲染 {len(pages)} 个模块页 + 总览页（第 {round_no} 轮）",
        )
        if patched:
            result.say("validate", f"本次渲染使用了 {len(patched)} 条自动补写内容")
        return result
