"""DocForge 入口：给一个代码目录，生成一份可交付的 API 文档。

用法：
    python run.py                        # 生成 examples/sample_pkg 的文档
    python run.py --src path/to/pkg      # 换一个目录
    python run.py --graph                # 只看流程（不执行）
    python run.py --from write           # 复用已有工件，从渲染阶段重跑
    python run.py --max-patch-rounds 0   # 关掉补写回边，观察循环守卫
    python run.py --json                 # 结束时输出机器可读摘要

作者：2323040304 张子炀
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from docforge import ArtifactStore, EventLog, Event, Pipeline, RunContext, RunOptions  # noqa: E402
from docforge.stages import build_pipeline  # noqa: E402

STUDENT = "2323040304 张子炀"
DEFAULT_SRC = HERE / "examples" / "sample_pkg"
DEFAULT_OUT = HERE / "out"

C_STAGE = "\033[36m"
C_OK = "\033[32m"
C_WARN = "\033[33m"
C_ERR = "\033[31m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_END = "\033[0m"


class Printer:
    """事件流的一个订阅者：把事件变成人能读的终端输出。"""

    def __init__(self, *, color: bool = True, verbose: bool = False, quiet: bool = False) -> None:
        self.tty = sys.stdout.isatty()
        self.color = color and self.tty and os.environ.get("NO_COLOR") is None
        self.verbose = verbose
        self.quiet = quiet
        self._seq = 0
        self._pending = ""

    def paint(self, text: str, color: str) -> str:
        return f"{color}{text}{C_END}" if self.color else text

    def __call__(self, event: Event) -> None:
        kind = event.kind
        if self.quiet and kind not in ("error",):
            return
        if kind == "run_start":
            print(self.paint(f"\n▶ {event.message}", C_BOLD))
            return
        if kind == "stage_start":
            self._seq += 1
            self._pending = f" [{self._seq:>2}] {event.stage:<13} {event.message}"
            if self.tty:
                print(self.paint(self._pending + " …", C_STAGE), end="", flush=True)
            return
        if kind == "stage_done":
            done = f"✓ {event.message}  {self.paint(f'({event.elapsed * 1000:.0f} ms)', C_DIM)}"
            if self.tty:
                print("\r\033[K" + self.paint(done, ""))
            else:
                print(self.paint(self._pending, C_STAGE) + " … " + self.paint(done, ""))
            return
        if kind == "detail":
            if self.verbose:
                print(self.paint(f"      · {event.message}", C_DIM))
            return
        if kind in ("retry", "warn"):
            print(self.paint(f"      ! {event.message}", C_WARN))
            return
        if kind == "guard":
            print(self.paint(f"      ! 循环守卫：{event.message}", C_WARN))
            return
        if kind == "branch":
            arrow = "↩" if event.data.get("goto") == "write" else "→"
            print(self.paint(f"      {arrow} {event.message}", C_STAGE))
            return
        if kind == "resume":
            print(self.paint(f"      ↺ {event.message}", C_STAGE))
            return
        if kind == "error":
            print(self.paint(f"\n✗ {event.message}", C_ERR))
            return
        if kind == "run_end":
            color = C_OK if event.data.get("status") == "completed" else C_ERR
            print("\n" + self.paint(f"■ {event.message}", color))
            return
        if self.verbose:
            print(self.paint(f"      · [{kind}] {event.message}", C_DIM))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="docforge",
        description="DocForge：代码 → 分析 → 文档 的文档生成工作流",
    )
    parser.add_argument("--src", default=str(DEFAULT_SRC), help="要生成文档的代码目录")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="输出目录（docs 与报告）")
    parser.add_argument("--max-patch-rounds", type=int, default=2, help="补写回边最多几轮")
    parser.add_argument("--threads", type=int, default=4, help="并行解析模块的线程数")
    parser.add_argument("--complexity-limit", type=int, default=8, help="复杂度告警阈值")
    parser.add_argument("--graph", action="store_true", help="只打印流程，不执行")
    parser.add_argument("--from", dest="start_stage", default=None, help="从指定阶段开始（复用已落盘工件）")
    parser.add_argument("--json", action="store_true", help="结束时输出 JSON 摘要")
    parser.add_argument("--verbose", "-v", action="store_true", help="显示细节事件")
    parser.add_argument("--quiet", "-q", action="store_true", help="只输出最终摘要")
    parser.add_argument("--no-color", action="store_true", help="关闭彩色输出")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    options = RunOptions(
        source=Path(args.src),
        out_dir=Path(args.out),
        max_patch_rounds=max(0, args.max_patch_rounds),
        threads=max(1, args.threads),
        start_stage=args.start_stage,
        quiet=args.quiet,
        student=STUDENT,
        complexity_limit=max(1, args.complexity_limit),
    )

    pipeline = build_pipeline(options)
    if args.graph:
        print(pipeline_ascii(pipeline))
        return 0

    out_dir = options.out_dir.expanduser().resolve()
    artifacts_dir = out_dir / "artifacts"
    events_path = out_dir / "events.jsonl"
    out_dir.mkdir(parents=True, exist_ok=True)

    store = ArtifactStore(dump_dir=artifacts_dir)
    if args.start_stage:
        restored = ArtifactStore.load(artifacts_dir)
        for key in restored.keys():
            store.put(key, restored.maybe(key), creator=f"restored:{key}")
        print(f"已从 {artifacts_dir} 恢复 {len(restored)} 个工件")

    log = EventLog(jsonl_path=events_path)
    printer = Printer(color=not args.no_color, verbose=args.verbose, quiet=options.quiet)
    log.subscribe(printer)

    ctx = RunContext(options=options, store=store, log=log)
    if not options.quiet:
        banner(options)
        print(pipeline_ascii(pipeline))

    started = time.perf_counter()
    summary = pipeline.run(ctx)
    elapsed = time.perf_counter() - started

    docs = ctx.store.maybe("docs", {}) or {}
    print_summary(summary, docs, elapsed, options)

    if args.json:
        print(json.dumps(
            {
                "status": summary.status,
                "stages_run": summary.stages_run,
                "rounds": summary.rounds,
                "guard_hits": summary.guard_hits,
                "duration": round(elapsed, 4),
                "coverage": docs.get("coverage", {}),
                "docs_dir": docs.get("dir", ""),
                "report": docs.get("report", ""),
                "artifacts": summary.artifacts,
                "error": summary.error,
            },
            ensure_ascii=False,
            indent=2,
        ))

    return 0 if summary.ok else 1


def banner(options: RunOptions) -> None:
    line = "=" * 74
    print(line)
    print(" DocForge · 代码 → 分析 → 文档（多 Agent 文档生成工作流）")
    print(f" 作者      : {options.student}")
    print(f" 扫描目录  : {options.source}")
    print(f" 输出目录  : {options.out_dir}")
    print(f" 补写轮次  : 最多 {options.max_patch_rounds} 轮 · 解析线程 {options.threads}")
    print(line)


def pipeline_ascii(pipeline: Pipeline) -> str:
    line = "-" * 74
    return f"\n{line}\n 流程\n{line}\n{pipeline.ascii()}\n{line}"


def print_summary(summary, docs: dict, elapsed: float, options: RunOptions) -> None:
    color = C_OK if summary.ok else C_ERR
    line = "=" * 74
    print()
    print(line)
    status = "完成" if summary.ok else "失败"
    print(f" 生成{'成功' if summary.ok else '失败'}：{status}（{elapsed:.2f}s）")
    print(f" 执行阶段 : {summary.stages_run} 次（含回边）")
    print(f" 补写循环 : {summary.rounds} 轮" + (f"（守卫触发 {summary.guard_hits} 次）" if summary.guard_hits else ""))
    coverage = docs.get("coverage", {})
    if coverage:
        print(
            f" 文档覆盖 : {coverage.get('percent', '?')}"
            f"（{coverage.get('documented', 0)}/{coverage.get('total', 0)}，"
            f"自动补写 {coverage.get('auto_filled', 0)} 项）"
        )
    if summary.error:
        print(f" 错误信息 : {summary.error}")
    if docs.get("dir"):
        print(f" 文档目录 : {docs['dir']}")
    if docs.get("report"):
        print(f" JSON 报告: {docs['report']}")
    print(f" 事件日志 : {Path(options.out_dir).expanduser().resolve() / 'events.jsonl'}")
    print(line)
    if not sys.stdout.isatty():
        return
    print(f"\033[{color}m{'生成完成' if summary.ok else '生成失败'}\033[0m")


if __name__ == "__main__":
    raise SystemExit(main())
