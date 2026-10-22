"""流水线的单元测试：顺序、分支回边、循环守卫、重试、失败策略、校验。"""

from __future__ import annotations

import unittest

from tests.fixtures import Broken, FlagOnce, FlagSetter, Flaky, Trace, make_context, tempdir

from docforge import Pipeline, PipelineError


class SequentialTest(unittest.TestCase):
    def test_runs_in_order(self):
        pipeline = Pipeline("t").add(Trace("a")).add(Trace("b")).add(Trace("c"))
        ctx = make_context(tempdir())
        summary = pipeline.run(ctx)

        self.assertEqual(summary.status, "completed")
        self.assertEqual(ctx.store.payload("trail"), ["a", "b", "c"])
        self.assertEqual(summary.stages_run, 3)
        self.assertEqual(summary.rounds, 0)

    def test_ascii_lists_all_stages(self):
        pipeline = Pipeline("t").add(Trace("a")).add(Trace("b"))
        text = pipeline.ascii()
        self.assertIn("a", text)
        self.assertIn("b", text)


class BranchLoopTest(unittest.TestCase):
    def test_branch_back_edge_runs_once(self):
        """补写一次后条件转假 → 只回边一次。"""
        pipeline = (
            Pipeline("t")
            .add(Trace("write"))
            .add(FlagOnce("validate", "need", True))
            .branch(
                name="decide",
                title="需要补写？",
                test=lambda ctx: bool(ctx.optional("need", False)),
                stage=FlagSetter("repair", "need", False),
                goto="write",
                max_rounds=2,
                otherwise="assemble",
            )
            .add(Trace("assemble"))
        )
        ctx = make_context(tempdir())
        summary = pipeline.run(ctx)

        self.assertEqual(summary.status, "completed")
        self.assertEqual(ctx.store.payload("trail"), ["write", "write", "assemble"])
        self.assertEqual(summary.rounds, 1)
        self.assertEqual(summary.guard_hits, 0)

    def test_guard_stops_endless_back_edge(self):
        """条件永远成立 → 触发守卫，不会死循环。"""
        pipeline = (
            Pipeline("t")
            .add(Trace("write"))
            .add(FlagSetter("validate", "need", True))
            .branch(
                name="decide",
                title="需要补写？",
                test=lambda ctx: True,
                stage=FlagSetter("repair", "need", True),
                goto="write",
                max_rounds=2,
                otherwise="assemble",
            )
            .add(Trace("assemble"))
        )
        ctx = make_context(tempdir())
        summary = pipeline.run(ctx)

        self.assertEqual(summary.status, "completed")
        self.assertEqual(summary.rounds, 2)
        self.assertEqual(summary.guard_hits, 1)
        self.assertEqual(ctx.store.payload("trail").count("assemble"), 1)

    def test_zero_rounds_guard_immediately(self):
        pipeline = (
            Pipeline("t")
            .add(Trace("write"))
            .branch(
                name="decide",
                title="需要补写？",
                test=lambda ctx: True,
                stage=Trace("repair"),
                goto="write",
                max_rounds=0,
                otherwise="assemble",
            )
            .add(Trace("assemble"))
        )
        ctx = make_context(tempdir())
        summary = pipeline.run(ctx)
        self.assertEqual(summary.rounds, 0)
        self.assertEqual(summary.guard_hits, 1)
        self.assertNotIn("repair", ctx.store.payload("trail"))


class FailureTest(unittest.TestCase):
    def test_retry_then_success(self):
        flaky = Flaky("flaky", fail_times=2)
        pipeline = Pipeline("t").add(flaky, retries=2)
        ctx = make_context(tempdir())
        summary = pipeline.run(ctx)

        self.assertEqual(summary.status, "completed")
        self.assertEqual(flaky.calls, 3)
        self.assertTrue(any(event.kind == "retry" for event in ctx.log.events))

    def test_abort_on_failure(self):
        pipeline = Pipeline("t").add(Broken()).add(Trace("after"))
        ctx = make_context(tempdir())
        summary = pipeline.run(ctx)

        self.assertEqual(summary.status, "failed")
        self.assertIn("阶段炸了", summary.error or "")
        self.assertFalse(ctx.store.has("trail"), "失败后不应继续执行后续阶段")

    def test_skip_on_failure(self):
        pipeline = Pipeline("t").add(Broken(), on_fail="skip").add(Trace("after"))
        ctx = make_context(tempdir())
        summary = pipeline.run(ctx)

        self.assertEqual(summary.status, "completed")
        self.assertEqual(ctx.store.payload("trail"), ["after"])
        self.assertTrue(any(event.kind == "warn" for event in ctx.log.events))

    def test_missing_artifact_fails_fast(self):
        pipeline = Pipeline("t").add(FlagSetter("boom", "x", 1))

        class NeedsMissing(Trace):
            def run(self, ctx):
                ctx.require("never_created")
                return super().run(ctx)

        pipeline.steps[0].stage = NeedsMissing("boom")
        ctx = make_context(tempdir())
        summary = pipeline.run(ctx)

        self.assertEqual(summary.status, "failed")
        self.assertIn("缺少上游工件", summary.error or "")


class ValidationTest(unittest.TestCase):
    def test_duplicate_names_rejected(self):
        pipeline = Pipeline("t").add(Trace("a")).add(Trace("a"))
        with self.assertRaises(PipelineError):
            pipeline.compile()

    def test_missing_back_edge_target_rejected(self):
        pipeline = Pipeline("t").add(Trace("a")).branch(
            name="decide", title="?", test=lambda ctx: False, stage=Trace("x"),
            goto="ghost", max_rounds=1,
        )
        with self.assertRaises(PipelineError):
            pipeline.compile()

    def test_forward_back_edge_rejected(self):
        """回边必须指回更早的阶段，指后面就是普通跳转，容易写错。"""
        pipeline = (
            Pipeline("t")
            .add(Trace("a"))
            .branch(name="decide", title="?", test=lambda ctx: False, stage=Trace("x"),
                    goto="later", max_rounds=1)
            .add(Trace("later"))
        )
        with self.assertRaises(PipelineError):
            pipeline.compile()

    def test_unknown_start_stage_rejected(self):
        pipeline = Pipeline("t").add(Trace("a"))
        ctx = make_context(tempdir(), start_stage="ghost")
        with self.assertRaises(PipelineError):
            pipeline.run(ctx)


if __name__ == "__main__":
    unittest.main()
