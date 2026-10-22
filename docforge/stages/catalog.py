"""catalog：把并行产出的模块事实汇总成一份目录。

并行的阶段彼此不知道对方的存在，所以必须有一步"汇合"，
这一层也顺便做统计，供后续校验与渲染使用。
"""

from __future__ import annotations

from ..context import RunContext
from ..quality import stats as build_stats
from ..stage import Stage, StageError, StageResult


class CatalogStage(Stage):
    name = "catalog"
    title = "汇总模块事实"

    def run(self, ctx: RunContext) -> StageResult:
        artifacts = [item for item in ctx.store.with_prefix("module:") if not item.name.endswith(":failures")]
        if not artifacts:
            raise StageError("没有解析结果（analyze 阶段可能全部失败）")

        modules = sorted((item.payload for item in artifacts), key=lambda item: item["module"])
        failures = ctx.optional("module:failures", []) or []
        patched = ctx.optional("patched", {}) or {}
        info = build_stats(modules, patched, ctx.options.complexity_limit)

        result = StageResult(
            artifacts={
                "catalog": {
                    "modules": modules,
                    "stats": info,
                    "failures": failures,
                }
            },
            message=(
                f"汇总 {info['modules']} 个模块：{info['classes']} 个类、{info['functions']} 个函数、"
                f"{info['symbols']} 个公开符号"
            ),
        )

        no_doc = [module["module"] for module in modules if not module.get("summary")]
        if no_doc:
            result.say("write", f"这些模块没有 docstring，请在文档中标注：{', '.join(no_doc)}")
        if failures:
            result.say("write", f"有 {len(failures)} 个模块解析失败，需要在文档中提醒读者")
        broken = [module["module"] for module in modules if module.get("syntax_error")]
        if broken:
            result.say("write", f"存在语法错误的模块：{', '.join(broken)}")
        return result
