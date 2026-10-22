"""scan：找出要生成文档的源码文件。"""

from __future__ import annotations

from pathlib import Path

from ..astlib import module_name_of
from ..context import RunContext
from ..stage import Stage, StageError, StageResult

SKIP_DIRS = {"__pycache__", ".git", ".venv", "venv", "build", "dist", "out", "node_modules"}


class ScanStage(Stage):
    name = "scan"
    title = "扫描源码目录"

    def run(self, ctx: RunContext) -> StageResult:
        root = Path(ctx.options.source).expanduser().resolve()
        if not root.is_dir():
            raise StageError(f"扫描目录不存在：{root}")

        base = root.parent  # 让模块名带上包前缀，例如 sample_pkg.metrics
        entries: list[dict] = []
        for path in sorted(root.rglob("*.py")):
            if any(part in SKIP_DIRS or part.startswith(".") for part in path.parts):
                continue
            try:
                source = path.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                ctx.log.emit("warn", f"读取失败，已跳过：{path}（{exc}）", stage=self.name)
                continue
            entries.append(
                {
                    "path": self._display_path(path, root),
                    "abs": str(path),
                    "module": module_name_of(path, base),
                    "source": source,
                    "lines": len(source.splitlines()),
                }
            )

        if not entries:
            raise StageError(f"目录 {root} 下没有找到 .py 文件")

        total_lines = sum(item["lines"] for item in entries)
        return StageResult(
            artifacts={
                "scan": {
                    "root": str(root),
                    "files": entries,
                    "count": len(entries),
                    "total_lines": total_lines,
                }
            },
            message=f"扫描到 {len(entries)} 个模块，共 {total_lines} 行",
        ).say("analyze", f"本次需要解析 {len(entries)} 个模块：{[item['module'] for item in entries]}")

    @staticmethod
    def _display_path(path: Path, root: Path) -> str:
        try:
            return str(path.relative_to(root))
        except ValueError:
            return str(path)
