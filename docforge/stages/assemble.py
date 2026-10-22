"""assemble：把渲染好的章节写成文件，并产出质量报告与 JSON 报告。"""

from __future__ import annotations

import json
from pathlib import Path

from ..context import RunContext
from ..quality import Gap
from ..render import module_filename, render_quality
from ..stage import Stage, StageError, StageResult


class AssembleStage(Stage):
    name = "assemble"
    title = "落盘文档与报告"

    def run(self, ctx: RunContext) -> StageResult:
        draft = ctx.require("draft")
        catalog = ctx.require("catalog")
        gaps_data = ctx.require("gaps")
        modules = catalog["modules"]
        patched = ctx.optional("patched", {}) or {}
        meta = draft.get("meta", {})

        out_dir = Path(ctx.options.out_dir).expanduser().resolve()
        docs_dir = out_dir / "docs"
        try:
            docs_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise StageError(f"无法创建输出目录 {docs_dir}：{exc}") from exc

        written: list[str] = []
        for module_name, text in draft["pages"].items():
            path = docs_dir / module_filename(module_name)
            path.write_text(text, encoding="utf-8")
            written.append(str(path))

        readme_path = docs_dir / "README.md"
        readme_path.write_text(draft["readme"], encoding="utf-8")
        written.append(str(readme_path))

        gaps = [Gap(**item) for item in gaps_data.get("items", [])]
        quality_text = render_quality(
            modules,
            gaps,
            meta=meta,
            patched=patched,
            rounds=ctx.rounds,
            generated_at=draft.get("generated_at", ""),
        )
        quality_path = docs_dir / "quality.md"
        quality_path.write_text(quality_text, encoding="utf-8")
        written.append(str(quality_path))

        report = {
            "generator": "DocForge",
            "author": ctx.options.student,
            "source": meta.get("source", ""),
            "generated_at": draft.get("generated_at", ""),
            "stats": catalog["stats"],
            "coverage": gaps_data.get("coverage", {}),
            "gaps": gaps_data.get("items", []),
            "patched": patched,
            "rounds": ctx.rounds,
            "guard_hits": ctx.guard_hits,
            "written": written,
            "artifacts": ctx.store.dump_summary(),
        }
        report_path = out_dir / "doc-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(str(report_path))

        coverage_info = gaps_data.get("coverage", {})
        return StageResult(
            artifacts={
                "docs": {
                    "dir": str(docs_dir),
                    "files": written,
                    "report": str(report_path),
                    "coverage": coverage_info,
                    "rounds": ctx.rounds,
                }
            },
            message=(
                f"写出 {len(written)} 个文件到 {docs_dir}（覆盖率 "
                f"{coverage_info.get('percent', '?')}，补写 {ctx.rounds} 轮）"
            ),
        )
