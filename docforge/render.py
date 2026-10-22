"""Markdown 渲染：只把已提取的事实排成文档，不做任何判断。

判断（哪些算缺口、覆盖率多少）在 quality.py；这里纯粹是"事实 → 文字"。
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable

from .astlib import classify_imports
from .quality import Gap, coverage, iter_symbols


def _clamp(text: str, limit: int) -> str:
    """表格里的长说明压缩成一行，超长就加省略号。"""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def module_filename(module: str) -> str:
    """模块名 → 文档文件名（点号换成下划线，所有页面平铺在 docs/ 下）。"""
    return module.replace(".", "_") + ".md"


def _cell(text: Any) -> str:
    """表格单元格转义：竖线会把 markdown 表格撑坏。"""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    if not rows:
        return "（无）"
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["------"] * len(headers)) + "|"]
    for row in rows:
        lines.append("| " + " | ".join(_cell(cell) for cell in row) + " |")
    return "\n".join(lines)


def _patched_entry(patched: dict[str, Any], module: str, qualname: str) -> dict[str, Any]:
    return patched.get(f"{module}:{qualname}", {}) or {}


def _description(module: str, symbol: dict[str, Any], patched: dict[str, Any]) -> str:
    if symbol.get("summary"):
        return symbol["summary"]
    entry = _patched_entry(patched, module, symbol["qualname"])
    if entry.get("summary"):
        return entry["summary"]
    return "⚠️ 缺少说明"


def _param_doc(module: str, symbol: dict[str, Any], param: str, patched: dict[str, Any]) -> str:
    args_doc = symbol.get("args_doc") or {}
    if param in args_doc:
        return args_doc[param]
    entry = _patched_entry(patched, module, symbol["qualname"])
    params = entry.get("params") or {}
    if param in params:
        return params[param] + "（自动补写）"
    return "—"


def _param_text(param: dict[str, Any], *, skip: tuple[str, ...] = ()) -> str:
    """把一个参数还原成 `name: type = default` 形式（表格里用）。"""
    if param.get("name") in skip:
        return ""
    text = param["name"]
    if param.get("annotation"):
        text += f": {param['annotation']}"
    if param.get("default"):
        text += f" = {param['default']}"
    if param.get("kind") == "var_positional":
        text = "*" + text
    elif param.get("kind") == "var_keyword":
        text = "**" + text
    return text


def _decorators(items: list[str] | None) -> str:
    return " ".join(f"`@{item}`" for item in (items or []) if item)


def _mermaid(edges: list[tuple[str, str]], title: str = "") -> str:
    if not edges:
        return ""
    lines = ["```mermaid", "flowchart LR"]
    for source, target in edges:
        src = re.sub(r"[^0-9A-Za-z_]", "_", source)
        dst = re.sub(r"[^0-9A-Za-z_]", "_", target)
        lines.append(f'    {src}["{source}"] --> {dst}["{target}"]')
    lines.append("```")
    return "\n".join(lines)


def render_module(module: dict[str, Any], patched: dict[str, Any], *, generated_at: str) -> str:
    """渲染单个模块的 Markdown。"""
    name = module["module"]
    functions = module.get("functions", [])
    classes = module.get("classes", [])
    symbols = list(iter_symbols(module))
    imports = classify_imports(
        [
            type(
                "Import",
                (),
                {
                    "module": item["module"],
                    "is_from": item["is_from"],
                    "relative": item["relative"],
                },
            )()
            for item in module.get("imports", [])
        ]
    )

    out: list[str] = [f"# `{name}`", ""]
    out.append(f"> 源文件 `{module['path']}` · {module['lines']} 行 · 生成于 {generated_at}")
    out.append("")

    summary = module.get("summary") or _patched_entry(patched, name, "(module)").get("summary")
    if summary:
        out.append(summary)
    elif module.get("docstring"):
        out.append(module["docstring"].splitlines()[0])
    else:
        out.append("> ⚠️ 该模块没有 docstring，本页只能列出结构。")
    out.append("")

    if module.get("syntax_error"):
        out.append(f"> ❌ 语法错误：{module['syntax_error']}（仅统计，未解析结构）")
        out.append("")

    out.append("## 结构速览")
    out.append("")
    out.append(
        _table(
            ["指标", "数值"],
            [
                ["类", len(classes)],
                ["函数", len(functions)],
                ["公开符号", len(symbols)],
                ["导入条目", len(module.get("imports", []))],
                ["TODO/FIXME", len(module.get("todos", []))],
                ["原生 docstring", sum(1 for s in symbols if s["has_doc"])],
                ["自动补写", sum(1 for s in symbols if not s["has_doc"] and _patched_entry(patched, name, s["qualname"]))],
            ],
        )
    )
    out.append("")

    out.append("## 依赖")
    out.append("")
    rows = [[bucket, "、".join(f"`{item}`" for item in modules)] for bucket, modules in imports.items() if modules]
    out.append(_table(["分类", "模块"], rows) if rows else "（无导入）")
    out.append("")

    if classes:
        out.append("## 类")
        out.append("")
        for klass in classes:
            bases = f"({', '.join(klass['bases'])})" if klass.get("bases") else ""
            out.append(f"### `{klass['name']}{bases}`")
            out.append("")
            decos = _decorators(klass.get("decorators"))
            if decos:
                out.append(f"装饰器：{decos}")
                out.append("")
            klass_symbol = {
                "qualname": klass["name"],
                "summary": klass.get("summary", ""),
                "args_doc": {},
            }
            out.append(_description(name, klass_symbol, patched))
            out.append("")
            if klass.get("attributes"):
                out.append(
                    _table(["属性", "类型"], [[attr, annot or "—"] for attr, annot in klass["attributes"]])
                )
                out.append("")
            if klass.get("methods"):
                method_rows = []
                for method in klass["methods"]:
                    params_text = ", ".join(
                        text
                        for text in (
                            _param_text(param, skip=("self", "cls"))
                            for param in method.get("params", [])
                        )
                        if text
                    )
                    method_symbol = {
                        "qualname": f"{klass['name']}.{method['name']}",
                        "summary": method.get("summary", ""),
                        "args_doc": method.get("args_doc", {}),
                    }
                    description = _description(name, method_symbol, patched)
                    method_rows.append(
                        [
                            f"`{method['name']}`",
                            params_text or "—",
                            method.get("returns") or "—",
                            description[:70],
                        ]
                    )
                out.append(_table(["方法", "参数", "返回", "说明"], method_rows))
                out.append("")

    if functions:
        out.append("## 函数")
        out.append("")
        for func in functions:
            prefix = "async " if func.get("is_async") else ""
            out.append(f"### `{prefix}{func['signature']}`" + (f" → `{func['returns']}`" if func.get("returns") else ""))
            out.append("")
            decos = _decorators(func.get("decorators"))
            if decos:
                out.append(f"装饰器：{decos}")
                out.append("")
            symbol = {
                "qualname": func["name"],
                "summary": func.get("summary", ""),
                "args_doc": func.get("args_doc", {}),
            }
            out.append(_description(name, symbol, patched))
            out.append("")
            visible_params = [p for p in func.get("params", []) if p["name"] not in ("self", "cls")]
            if visible_params:
                out.append(
                    _table(
                        ["参数", "类型", "默认值", "说明"],
                        [
                            [
                                f"`{param['name']}`",
                                f"`{param['annotation']}`" if param.get("annotation") else "—",
                                f"`{param['default']}`" if param.get("default") else "—",
                                _param_doc(name, symbol, param["name"], patched),
                            ]
                            for param in visible_params
                        ],
                    )
                )
                out.append("")
            if func.get("returns_doc"):
                out.append(f"**返回**：{func['returns_doc']}")
                out.append("")
            if func.get("raises"):
                out.append(
                    _table(
                        ["异常", "触发条件"],
                        [[f"`{item['name']}`", item.get("description") or "—"] for item in func["raises"]],
                    )
                )
                out.append("")
            if func.get("examples"):
                out.append("**示例**")
                out.append("")
                out.append("```python")
                out.append(func["examples"].strip())
                out.append("```")
                out.append("")

    edges = [(func["name"], call.split(".")[-1]) for func in functions for call in func.get("calls", [])]
    defined = {func["name"] for func in functions} | {klass["name"] for klass in classes}
    edges = sorted({(a, b) for a, b in edges if b in defined and a != b})
    if edges:
        out.append("## 调用关系")
        out.append("")
        out.append(_mermaid(edges))
        out.append("")

    risks: list[str] = []
    for todo in module.get("todos", []):
        risks.append(f"- 第 {todo['lineno']} 行 `{todo['kind']}`：{todo['text'] or '（无说明）'}")
    for symbol in sorted(symbols, key=lambda item: item["complexity"], reverse=True)[:3]:
        if symbol["complexity"] > 8:
            risks.append(
                f"- `{symbol['qualname']}` 复杂度 {symbol['complexity']}（第 {symbol['lineno']} 行），建议拆分"
            )
    out.append("## 待办与风险")
    out.append("")
    out.append("\n".join(risks) if risks else "（无）")
    out.append("")
    return "\n".join(out)


def render_readme(
    modules: list[dict[str, Any]],
    *,
    meta: dict[str, Any],
    patched: dict[str, Any],
    generated_at: str,
) -> str:
    """渲染总览页（各模块文档的入口）。"""
    from .quality import stats as build_stats

    info = build_stats(modules, patched, meta.get("complexity_limit", 8))
    cov = info["coverage"]

    out = ["# 项目 API 文档", ""]
    out.append(_table(
        ["项目", "内容"],
        [
            ["文档生成器", "DocForge（代码 → 分析 → 文档）"],
            ["作者", meta.get("student", "")],
            ["扫描目录", f"`{meta.get('source', '')}`"],
            ["模块数", info["modules"]],
            ["生成时间", generated_at],
        ],
    ))
    out.append("")

    out.append("## 文档覆盖情况")
    out.append("")
    out.append(_table(
        ["指标", "数值"],
        [
            ["公开符号", cov["total"]],
            ["有说明", cov["documented"]],
            ["其中自动补写", cov["auto_filled"]],
            ["仍缺说明", cov["missing"]],
            ["覆盖率", cov["percent"]],
            ["代码行数", info["lines"]],
            ["类 / 函数 / 方法", f"{info['classes']} / {info['functions']} / {info['methods']}"],
            ["TODO/FIXME", info["todos"]],
        ],
    ))
    out.append("")

    out.append("## 模块索引")
    out.append("")
    rows = []
    for module in modules:
        rows.append(
            [
                f"[`{module['module']}`]({module_filename(module['module'])})",
                _clamp(module.get("summary") or "⚠️ 无模块说明", 46),
                len(module.get("classes", [])),
                len(module.get("functions", [])),
                module.get("lines", 0),
            ]
        )
    out.append(_table(["模块", "说明", "类", "函数", "行数"], rows))
    out.append("")
    auto_rows = [
        [f"`{key.split(':', 1)[1]}`", key.split(":", 1)[0], _clamp(entry.get("summary", ""), 56)]
        for key, entry in sorted(patched.items())
        if entry.get("summary")
    ]
    if auto_rows:
        out.append("## 自动补写的条目（需人工确认）")
        out.append("")
        out.append(_table(["符号", "模块", "补写的说明"], auto_rows))
        out.append("")

    if info["high_complexity"]:
        out.append("## 复杂度偏高的符号")
        out.append("")
        out.append(_table(
            ["模块", "符号", "复杂度", "行号"],
            [
                [item["module"], f"`{item['qualname']}`", item["complexity"], item["lineno"]]
                for item in info["high_complexity"][:10]
            ],
        ))
        out.append("")

    todos = [
        [module["module"], todo["lineno"], todo["kind"], todo["text"] or "—"]
        for module in modules
        for todo in module.get("todos", [])
    ]
    if todos:
        out.append("## 待办汇总")
        out.append("")
        out.append(_table(["模块", "行号", "类型", "内容"], todos))
        out.append("")
    return "\n".join(out)


def render_quality(
    modules: list[dict[str, Any]],
    gaps: Iterable[Gap],
    *,
    meta: dict[str, Any],
    patched: dict[str, Any],
    rounds: int,
    generated_at: str,
) -> str:
    """渲染质量报告：覆盖率、缺口清单、补写记录、结论。"""
    from .quality import BLOCKING, stats as build_stats

    gaps = list(gaps)
    info = build_stats(modules, patched, meta.get("complexity_limit", 8))
    cov = info["coverage"]
    blocking = [gap for gap in gaps if gap.severity == BLOCKING]

    if not blocking:
        verdict = "✅ 通过：所有公开符号都有说明（其中自动补写项建议人工确认）"
    else:
        verdict = f"⚠️ 未通过：仍有 {len(blocking)} 个公开符号缺少说明"

    out = ["# 文档质量报告", ""]
    out.append(verdict)
    out.append("")
    out.append(_table(
        ["指标", "数值"],
        [
            ["覆盖率", cov["percent"]],
            ["公开符号", cov["total"]],
            ["有说明", cov["documented"]],
            ["自动补写", cov["auto_filled"]],
            ["缺口总数", len(gaps)],
            ["阻断级缺口", len(blocking)],
            ["补写循环轮次", rounds],
            ["生成时间", generated_at],
        ],
    ))
    out.append("")
    out.append("## 缺口清单")
    out.append("")
    out.append(_table(
        ["级别", "模块", "符号", "类型", "说明"],
        [
            [
                "阻断" if gap.severity == BLOCKING else "建议",
                gap.module,
                f"`{gap.qualname}`",
                gap.kind,
                gap.detail,
            ]
            for gap in gaps
        ],
    ))
    out.append("")

    if patched:
        out.append("## 自动补写记录")
        out.append("")
        out.append(_table(
            ["符号", "模块", "补写内容"],
            [
                [f"`{key.split(':', 1)[1]}`", key.split(":", 1)[0], entry.get("summary", "")]
                for key, entry in sorted(patched.items())
            ],
        ))
        out.append("")
        out.append("> 自动补写只是为了让文档结构完整，**语义仍需人工确认**。")
        out.append("")
    return "\n".join(out)
