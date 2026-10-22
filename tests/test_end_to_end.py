"""端到端测试：真跑一遍流程，检查产物；再测 --from 重跑与循环守卫。"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from tests.fixtures import EXAMPLES, make_context, tempdir

from docforge import ArtifactStore, EventLog, RunContext, RunOptions
from docforge.stages import build_pipeline

import run as cli


def run_pipeline(tmp: Path, *, max_patch_rounds: int = 2, start_stage: str | None = None,
                 store: ArtifactStore | None = None) -> tuple[object, RunContext]:
    options = RunOptions(
        source=EXAMPLES,
        out_dir=tmp / "out",
        max_patch_rounds=max_patch_rounds,
        threads=3,
        start_stage=start_stage,
    )
    pipeline = build_pipeline(options)
    ctx = RunContext(
        options=options,
        store=store or ArtifactStore(dump_dir=tmp / "artifacts"),
        log=EventLog(jsonl_path=tmp / "events.jsonl"),
    )
    return pipeline.run(ctx), ctx


class FullRunTest(unittest.TestCase):
    def test_end_to_end_generates_docs(self):
        tmp = tempdir()
        summary, ctx = run_pipeline(tmp)

        self.assertEqual(summary.status, "completed")
        self.assertEqual(summary.rounds, 1, "缺文档 → 补写一轮 → 收敛")
        self.assertEqual(summary.guard_hits, 0)

        docs_dir = tmp / "out" / "docs"
        readme = docs_dir / "README.md"
        self.assertTrue(readme.is_file())
        text = readme.read_text(encoding="utf-8")
        self.assertIn("项目 API 文档", text)
        self.assertIn("模块索引", text)
        self.assertIn("100.0%", text)

        # 每个模块一页
        pages = sorted(path.name for path in docs_dir.glob("sample_pkg*.md"))
        self.assertIn("sample_pkg_models.md", pages)
        self.assertIn("sample_pkg_pricing.md", pages)

        # 质量页与 JSON 报告
        self.assertTrue((docs_dir / "quality.md").is_file())
        report = json.loads((tmp / "out" / "doc-report.json").read_text(encoding="utf-8"))
        self.assertEqual(report["generator"], "DocForge")
        self.assertEqual(report["coverage"]["ratio"], 1.0)
        self.assertEqual(report["rounds"], 1)
        self.assertIn("scan", report["artifacts"])

    def test_events_written(self):
        tmp = tempdir()
        run_pipeline(tmp)
        lines = (tmp / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
        kinds = [json.loads(line)["kind"] for line in lines]
        self.assertIn("run_start", kinds)
        self.assertIn("stage_done", kinds)
        self.assertIn("branch", kinds)
        self.assertIn("run_end", kinds)

    def test_guard_mode_leaves_gaps(self):
        tmp = tempdir()
        summary, ctx = run_pipeline(tmp, max_patch_rounds=0)

        self.assertEqual(summary.status, "completed")
        self.assertEqual(summary.rounds, 0)
        self.assertEqual(summary.guard_hits, 1, "0 轮上限应立即触发守卫")
        coverage = ctx.require("gaps")["coverage"]
        self.assertLess(coverage["ratio"], 1.0)
        quality = (tmp / "out" / "docs" / "quality.md").read_text(encoding="utf-8")
        self.assertIn("未通过", quality)


class ReplayTest(unittest.TestCase):
    def test_from_write_reuses_artifacts(self):
        tmp = tempdir()
        run_pipeline(tmp)

        restored = ArtifactStore.load(tmp / "artifacts")
        self.assertTrue(restored.has("catalog"))
        self.assertTrue(restored.has("module:sample_pkg.models"))

        summary, ctx = run_pipeline(tmp, start_stage="write", store=restored)
        self.assertEqual(summary.status, "completed")
        self.assertEqual(summary.stages_run, 4, "write/validate/decide/assemble 四步")
        self.assertTrue((tmp / "out" / "docs" / "README.md").is_file())


class CliTest(unittest.TestCase):
    def test_graph_only(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["--graph"])
        self.assertEqual(code, 0)
        output = buffer.getvalue()
        self.assertIn("scan", output)
        self.assertIn("回边", output)

    def test_cli_json_output(self):
        tmp = tempdir()
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = cli.main(["--src", str(EXAMPLES), "--out", str(tmp / "out"), "--json", "--no-color"])
        self.assertEqual(code, 0)
        payload = buffer.getvalue()
        self.assertIn('"status": "completed"', payload)
        self.assertIn('"rounds": 1', payload)
        self.assertTrue((tmp / "out" / "docs" / "README.md").is_file())

    def test_cli_failure_returns_nonzero(self):
        tmp = tempdir()
        empty = tmp / "empty"
        empty.mkdir()
        with redirect_stdout(io.StringIO()):
            code = cli.main(["--src", str(empty), "--out", str(tmp / "out"), "--no-color"])
        self.assertEqual(code, 1, "空目录应该失败并返回非 0")


if __name__ == "__main__":
    unittest.main()
