"""astlib 的单元测试：签名、docstring 解析、依赖分类、复杂度、待办。"""

from __future__ import annotations

import unittest

from tests.fixtures import EXAMPLES

from docforge.astlib import (
    classify_imports,
    count_complexity,
    module_name_of,
    parse_docstring,
    parse_file,
    parse_source,
)

SAMPLE = '''
"""模块说明：演示用的示例模块。"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from .helpers import slugify

TODO_TAG = "x"  # TODO: 改成配置


def fetch(url: str, timeout: int = 5, *, retry: bool = False) -> dict:
    """抓取并解析 JSON。

    Args:
        url: 目标地址。
        timeout: 超时秒数。
        retry: 失败是否重试。

    Returns:
        解析后的字典。

    Raises:
        ValueError: 返回内容不是 JSON 时。

    Examples:
        >>> fetch("http://x")
        {}
    """
    if not url:
        raise ValueError("url 不能为空")
    data = json.loads("{}")
    for _ in range(3):
        data.update({})
    return data


def _internal() -> None:
    pass


class Client:
    """一个客户端。

    Args:
        base: 基地址。
    """

    version = "1.0"

    def get(self, path: str) -> str:
        return path

    def _private(self) -> None:
        pass
'''


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.info = parse_source(SAMPLE, path="pkg/demo.py", root=".")

    def test_module_basics(self):
        self.assertEqual(self.info.module, "pkg.demo")
        self.assertIn("模块说明", self.info.summary)
        self.assertEqual(self.info.lines, len(SAMPLE.splitlines()))
        self.assertEqual(self.info.syntax_error, "")

    def test_imports_collected_and_classified(self):
        modules = [item.module for item in self.info.imports]
        self.assertIn("json", modules)
        self.assertIn("yaml", modules)
        self.assertIn("helpers", modules)
        buckets = classify_imports(self.info.imports)
        self.assertIn("json", buckets["标准库"])
        self.assertIn("yaml", buckets["第三方"])
        self.assertIn("helpers", buckets["项目内"])
        # __future__ 是编译指令，不该出现在依赖里
        self.assertNotIn("__future__", sum(buckets.values(), []))

    def test_function_signature_and_params(self):
        fetch = self.info.functions[0]
        self.assertEqual(fetch.name, "fetch")
        self.assertIn("url: str", fetch.signature)
        self.assertIn("timeout: int = 5", fetch.signature)
        self.assertIn("retry: bool = False", fetch.signature)
        self.assertEqual(fetch.returns, "dict")
        kinds = {param.name: param.kind for param in fetch.params}
        self.assertEqual(kinds["retry"], "keyword_only")
        self.assertEqual(kinds["url"], "positional")

    def test_docstring_sections(self):
        fetch = self.info.functions[0]
        self.assertEqual(fetch.summary, "抓取并解析 JSON。")
        self.assertEqual(fetch.args_doc["url"], "目标地址。")
        self.assertEqual(fetch.args_doc["retry"], "失败是否重试。")
        self.assertIn("解析后的字典", fetch.returns_doc)
        self.assertEqual([item.name for item in fetch.raises], ["ValueError"])
        self.assertIn("fetch(", fetch.examples)

    def test_visibility(self):
        names = {item.name: item.is_public for item in self.info.functions}
        self.assertTrue(names["fetch"])
        self.assertFalse(names["_internal"])
        klass = self.info.classes[0]
        self.assertEqual(klass.name, "Client")
        self.assertEqual([method.name for method in klass.methods], ["get", "_private"])
        self.assertFalse(klass.methods[1].is_public)

    def test_complexity_counts_branches(self):
        fetch = self.info.functions[0]
        self.assertGreater(fetch.complexity, 1)
        self.assertEqual(count_complexity(__import__("ast").parse("x = 1").body[0]), 1)

    def test_todo_collected(self):
        self.assertEqual(len(self.info.todos), 1)
        self.assertEqual(self.info.todos[0].kind, "TODO")
        self.assertIn("改成配置", self.info.todos[0].text)

    def test_to_dict_is_json_ready(self):
        import json

        payload = self.info.to_dict()
        text = json.dumps(payload, ensure_ascii=False)
        self.assertIn("Client", text)
        self.assertIn("fetch", text)

    def test_calls_collected(self):
        fetch = self.info.functions[0]
        self.assertIn("json.loads", fetch.calls)


class EdgeCaseTest(unittest.TestCase):
    def test_syntax_error_is_captured_not_raised(self):
        info = parse_source("def broken(:\n", path="x.py", root=".")
        self.assertIn("第 1 行", info.syntax_error)
        self.assertEqual(info.functions, [])

    def test_empty_docstring_sections(self):
        parsed = parse_docstring("只有一句话")
        self.assertEqual(parsed.summary, "只有一句话")
        self.assertEqual(parsed.args, {})

    def test_docstring_with_continuation_lines(self):
        parsed = parse_docstring(
            "做一件事。\n\nArgs:\n    value: 第一行说明，\n        第二行接着写。\n\nReturns:\n    结果。\n"
        )
        self.assertIn("第一行说明", parsed.args["value"])
        self.assertIn("第二行接着写", parsed.args["value"])
        self.assertEqual(parsed.returns, "结果。")

    def test_module_name_for_init(self):
        self.assertEqual(module_name_of(EXAMPLES / "__init__.py", EXAMPLES.parent), "sample_pkg")
        self.assertEqual(module_name_of(EXAMPLES / "models.py", EXAMPLES.parent), "sample_pkg.models")

    def test_parse_real_example_package(self):
        infos = [parse_file(path, EXAMPLES.parent) for path in sorted(EXAMPLES.glob("*.py"))]
        self.assertGreaterEqual(len(infos), 4)
        for info in infos:
            self.assertEqual(info.syntax_error, "", f"{info.module} 不应有语法错误")
            self.assertTrue(info.docstring, f"{info.module} 应该有模块 docstring")


if __name__ == "__main__":
    unittest.main()
