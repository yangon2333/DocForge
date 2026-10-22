"""质量计算与 Markdown 渲染的单元测试。"""

from __future__ import annotations

import unittest

from tests.fixtures import EXAMPLES

from docforge.astlib import parse_file
from docforge.quality import (
    BLOCKING,
    blocking_gaps,
    coverage,
    find_gaps,
    iter_symbols,
    stats,
)
from docforge.render import module_filename, render_module, render_quality, render_readme


def load_modules():
    return [
        parse_file(path, EXAMPLES.parent).to_dict()
        for path in sorted(EXAMPLES.glob("*.py"))
    ]


class QualityTest(unittest.TestCase):
    def setUp(self):
        self.modules = load_modules()
        self.patched = {}

    def test_symbols_count_public_only(self):
        names = [symbol["qualname"] for module in self.modules for symbol in iter_symbols(module)]
        self.assertIn("compute_total", names)
        self.assertIn("OrderStore.save", names)
        self.assertNotIn("OrderStore.__init__", names, "下划线开头的方法不算公开符号")

    def test_gaps_found_for_missing_docstrings(self):
        gaps = find_gaps(self.modules, self.patched)
        blocking = blocking_gaps(gaps)
        self.assertGreaterEqual(len(blocking), 3)
        self.assertTrue(all(gap.kind == "symbol-docstring" for gap in blocking))
        self.assertTrue(all(gap.severity == BLOCKING for gap in blocking))

    def test_coverage_improves_after_patch(self):
        before = coverage(self.modules, self.patched)
        self.assertLess(before["ratio"], 1.0)

        patched = {
            f"{gap.module}:{gap.qualname}": {"summary": "自动补写"}
            for gap in blocking_gaps(find_gaps(self.modules, self.patched))
        }
        after = coverage(self.modules, patched)
        self.assertEqual(after["ratio"], 1.0)
        self.assertEqual(after["auto_filled"], before["missing"])
        self.assertEqual(blocking_gaps(find_gaps(self.modules, patched)), [])

    def test_stats_counts(self):
        info = stats(self.modules, self.patched, complexity_limit=1)
        self.assertEqual(info["modules"], 4)
        self.assertGreater(info["lines"], 100)
        self.assertGreater(info["symbols"], 5)
        self.assertGreaterEqual(info["todos"], 1)
        self.assertTrue(info["high_complexity"], "阈值设为 1 时应该有高复杂度符号")


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.modules = {module["module"]: module for module in load_modules()}
        self.patched = {"sample_pkg.models:OrderLine.is_valid": {"summary": "判断明细是否合法（自动补写，待人工确认）"}}

    def test_module_page_structure(self):
        text = render_module(self.modules["sample_pkg.models"], self.patched, generated_at="2026-01-01 00:00:00")
        self.assertIn("# `sample_pkg.models`", text)
        self.assertIn("## 结构速览", text)
        self.assertIn("## 依赖", text)
        self.assertIn("## 类", text)
        self.assertIn("一条订单明细。", text)
        self.assertIn("| 方法 | 参数 | 返回 | 说明 |", text)

    def test_method_params_exclude_self(self):
        text = render_module(self.modules["sample_pkg.models"], self.patched, generated_at="t")
        self.assertNotIn("| `subtotal` | self |", text)
        self.assertIn("| `add_line` | line: OrderLine |", text)

    def test_auto_filled_marked_once(self):
        text = render_module(self.modules["sample_pkg.models"], self.patched, generated_at="t")
        self.assertIn("自动补写，待人工确认", text)
        self.assertEqual(text.count("（自动补写，待人工确认）（自动补写，待人工确认）"), 0)

    def test_readme_has_index_and_links(self):
        ordered = list(self.modules.values())
        text = render_readme(ordered, meta={"student": "学号 姓名", "source": "examples"},
                             patched=self.patched, generated_at="t")
        self.assertIn("## 模块索引", text)
        self.assertIn(f"]({module_filename('sample_pkg.models')})", text)
        self.assertIn("## 自动补写的条目（需人工确认）", text)
        self.assertIn("学号 姓名", text)

    def test_quality_verdict(self):
        gaps = find_gaps(list(self.modules.values()), {})
        text = render_quality(list(self.modules.values()), gaps, meta={}, patched={}, rounds=0,
                              generated_at="t")
        self.assertIn("未通过", text)
        self.assertIn("阻断", text)

    def test_table_escapes_pipes(self):
        module = dict(self.modules["sample_pkg.pricing"])
        functions = [dict(item) for item in module["functions"]]
        for func in functions:
            if func["name"] == "compute_total":
                func["args_doc"] = {"order": "含竖线 | 的说明"}
        module["functions"] = functions
        text = render_module(module, {}, generated_at="t")
        self.assertIn("含竖线 \\| 的说明", text)

    def test_module_filename_flat(self):
        self.assertEqual(module_filename("a.b.c"), "a_b_c.md")


if __name__ == "__main__":
    unittest.main()
