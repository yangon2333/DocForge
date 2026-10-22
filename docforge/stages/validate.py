"""validate：检查文档有没有"该说而没说"的地方，给出覆盖率与缺口清单。"""

from __future__ import annotations

from ..context import RunContext
from ..quality import BLOCKING, blocking_gaps, coverage, find_gaps
from ..stage import Stage, StageResult


class ValidateStage(Stage):
    name = "validate"
    title = "校验文档覆盖率"

    def run(self, ctx: RunContext) -> StageResult:
        modules = ctx.require("catalog")["modules"]
        patched = ctx.optional("patched", {}) or {}

        gaps = find_gaps(modules, patched)
        blocking = blocking_gaps(gaps)
        cov = coverage(modules, patched)

        result = StageResult(
            artifacts={
                "gaps": {
                    "items": [gap.to_dict() for gap in gaps],
                    "blocking": len(blocking),
                    "total": len(gaps),
                    "coverage": cov,
                }
            },
            message=(
                f"覆盖率 {cov['percent']}（{cov['documented']}/{cov['total']}），"
                f"阻断缺口 {len(blocking)} 个、建议 {len(gaps) - len(blocking)} 个"
            ),
        )

        if blocking:
            names = "、".join(gap.qualname for gap in blocking[:8])
            more = " 等" if len(blocking) > 8 else ""
            result.say("repair", f"需要补写 {len(blocking)} 个符号的说明：{names}{more}")
            ctx.log.emit(
                "detail",
                f"阻断级缺口：{[gap.qualname for gap in blocking][:10]}",
                stage=self.name,
            )
        else:
            advisory = [gap for gap in gaps if gap.severity != BLOCKING]
            if advisory:
                ctx.log.emit(
                    "detail",
                    f"只剩建议级缺口 {len(advisory)} 个（不阻断交付，例如参数未逐一说明）",
                    stage=self.name,
                )
        return result
