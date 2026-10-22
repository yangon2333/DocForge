"""AST 提取：把 Python 源码解析成"结构化事实"，供后续阶段渲染文档。

这一层只做**事实提取**，不做任何排版、判断或文案生成，因此可以单独测试。
事实一旦提取出来，文档生成就变成纯字符串拼装，结果可复现。
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SECTIONS = {
    "args": "args",
    "arguments": "args",
    "parameters": "args",
    "params": "args",
    "returns": "returns",
    "return": "returns",
    "yields": "returns",
    "raises": "raises",
    "exceptions": "raises",
    "example": "examples",
    "examples": "examples",
    "usage": "examples",
    "attributes": "attributes",
    "note": "note",
    "notes": "note",
}

TODO_PATTERN = re.compile(r"\b(TODO|FIXME|XXX|HACK)\b[:\s]*(.*)", re.IGNORECASE)
COMPLEXITY_NODES = (
    ast.If,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.Try,
    ast.With,
    ast.AsyncWith,
    ast.BoolOp,
    ast.IfExp,
    ast.ExceptHandler,
    ast.comprehension,
)
STDLIB_HINT = {
    "abc", "argparse", "ast", "asyncio", "base64", "collections", "concurrent", "contextlib",
    "copy", "csv", "dataclasses", "datetime", "decimal", "enum", "functools", "glob", "hashlib",
    "html", "http", "io", "itertools", "json", "logging", "math", "operator", "os", "pathlib",
    "pickle", "random", "re", "shutil", "sqlite3", "statistics", "string", "subprocess", "sys",
    "tempfile", "textwrap", "threading", "time", "typing", "unittest", "urllib", "uuid", "warnings",
    "xml", "zipfile",
}


# ====================================================================== 数据结构
@dataclass
class ParamInfo:
    name: str
    annotation: str = ""
    default: str = ""
    kind: str = "positional"  # positional / keyword_only / var_positional / var_keyword

    def render(self) -> str:
        text = self.name
        if self.annotation:
            text += f": {self.annotation}"
        if self.default:
            text += f" = {self.default}"
        if self.kind == "var_positional":
            text = "*" + text
        elif self.kind == "var_keyword":
            text = "**" + text
        return text


@dataclass
class RaiseInfo:
    name: str
    description: str = ""


@dataclass
class FunctionInfo:
    name: str
    lineno: int
    signature: str
    params: list[ParamInfo] = field(default_factory=list)
    returns: str = ""
    decorators: list[str] = field(default_factory=list)
    is_async: bool = False
    is_public: bool = True
    is_method: bool = False
    docstring: str = ""
    summary: str = ""
    args_doc: dict[str, str] = field(default_factory=dict)
    returns_doc: str = ""
    raises: list[RaiseInfo] = field(default_factory=list)
    examples: str = ""
    calls: list[str] = field(default_factory=list)
    complexity: int = 1
    lines: int = 0


@dataclass
class ClassInfo:
    name: str
    lineno: int
    bases: list[str] = field(default_factory=list)
    decorators: list[str] = field(default_factory=list)
    docstring: str = ""
    summary: str = ""
    is_public: bool = True
    methods: list[FunctionInfo] = field(default_factory=list)
    attributes: list[tuple[str, str]] = field(default_factory=list)
    lines: int = 0


@dataclass
class ImportInfo:
    module: str
    lineno: int
    names: list[str] = field(default_factory=list)
    is_from: bool = False
    relative: bool = False

    @property
    def text(self) -> str:
        prefix = "." * (self.module.count(".") if self.relative else 0)
        if self.is_from:
            return f"from {prefix}{self.module} import {', '.join(self.names)}"
        return f"import {self.module}"


@dataclass
class TodoInfo:
    kind: str
    text: str
    lineno: int


@dataclass
class DocString:
    summary: str = ""
    args: dict[str, str] = field(default_factory=dict)
    returns: str = ""
    raises: list[RaiseInfo] = field(default_factory=list)
    examples: str = ""


@dataclass
class ModuleInfo:
    path: str
    module: str
    docstring: str = ""
    summary: str = ""
    imports: list[ImportInfo] = field(default_factory=list)
    classes: list[ClassInfo] = field(default_factory=list)
    functions: list[FunctionInfo] = field(default_factory=list)
    todos: list[TodoInfo] = field(default_factory=list)
    lines: int = 0
    syntax_error: str = ""

    # ---------------------------------------------------------------- 便捷查询
    @property
    def public_functions(self) -> list[FunctionInfo]:
        return [item for item in self.functions if item.is_public]

    @property
    def public_classes(self) -> list[ClassInfo]:
        return [item for item in self.classes if item.is_public]

    def iter_functions(self) -> Iterable[FunctionInfo]:
        yield from self.functions
        for klass in self.classes:
            yield from klass.methods

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "module": self.module,
            "docstring": self.docstring,
            "summary": self.summary,
            "lines": self.lines,
            "syntax_error": self.syntax_error,
            "imports": [
                {"module": item.module, "names": item.names, "is_from": item.is_from,
                 "relative": item.relative, "lineno": item.lineno}
                for item in self.imports
            ],
            "todos": [{"kind": t.kind, "text": t.text, "lineno": t.lineno} for t in self.todos],
            "classes": [
                {
                    "name": k.name, "lineno": k.lineno, "bases": k.bases,
                    "decorators": k.decorators,
                    "docstring": k.docstring, "summary": k.summary,
                    "is_public": k.is_public,
                    "lines": k.lines, "attributes": [list(a) for a in k.attributes],
                    "methods": [_function_to_dict(m) for m in k.methods],
                }
                for k in self.classes
            ],
            "functions": [_function_to_dict(f) for f in self.functions],
        }


def _function_to_dict(func: FunctionInfo) -> dict[str, Any]:
    return {
        "name": func.name,
        "lineno": func.lineno,
        "signature": func.signature,
        "returns": func.returns,
        "decorators": func.decorators,
        "is_async": func.is_async,
        "is_public": func.is_public,
        "is_method": func.is_method,
        "docstring": func.docstring,
        "summary": func.summary,
        "args_doc": func.args_doc,
        "returns_doc": func.returns_doc,
        "raises": [{"name": r.name, "description": r.description} for r in func.raises],
        "examples": func.examples,
        "calls": func.calls,
        "complexity": func.complexity,
        "lines": func.lines,
        "params": [
            {"name": p.name, "annotation": p.annotation, "default": p.default, "kind": p.kind}
            for p in func.params
        ],
    }


# ====================================================================== 文档字符串
def parse_docstring(text: str) -> DocString:
    """解析 Google 风格 docstring 的常见段落。"""
    info = DocString()
    if not text:
        return info

    lines = [line.rstrip() for line in text.strip().splitlines()]
    section = ""
    buffer: list[str] = []
    summary_lines: list[str] = []
    in_summary = True
    current_key = ""
    current_indent = 0

    def flush() -> None:
        nonlocal buffer, current_key, current_indent
        if not section:
            buffer = []
            return
        content = "\n".join(buffer).strip()
        if section == "args" and current_key:
            info.args[current_key] = " ".join(content.split())
        elif section == "returns" and content:
            info.returns = " ".join(content.split())
        elif section == "raises" and current_key:
            info.raises.append(RaiseInfo(name=current_key, description=" ".join(content.split())))
        elif section == "examples" and content:
            info.examples = (info.examples + "\n" + content).strip()
        buffer = []
        current_key = ""
        current_indent = 0

    for raw in lines:
        stripped = raw.strip()
        header = stripped[:-1].strip().lower() if stripped.endswith(":") else ""
        if header in SECTIONS:
            flush()
            section = SECTIONS[header]
            in_summary = False
            continue
        if not stripped:
            if in_summary:
                continue
            buffer.append("")
            continue
        if in_summary:
            summary_lines.append(stripped)
            continue

        indent = len(raw) - len(raw.lstrip())
        if section == "args":
            match = re.match(r"^(\*{0,2}\w+)\s*(\(([^)]*)\))?\s*:\s*(.*)$", stripped)
            if match:
                flush()
                current_key = match.group(1).lstrip("*")
                current_indent = indent
                buffer.append(match.group(4))
            elif indent > current_indent and current_key:
                buffer.append(stripped)
            else:
                buffer.append(stripped)
        elif section == "raises":
            match = re.match(r"^([\w.]+)\s*:\s*(.*)$", stripped)
            if match:
                flush()
                current_key = match.group(1)
                current_indent = indent
                buffer.append(match.group(2))
            elif current_key:
                buffer.append(stripped)
        else:
            buffer.append(stripped)

    flush()
    info.summary = " ".join(summary_lines).strip()
    return info


# ====================================================================== 提取
def parse_file(path: Path, root: Path) -> ModuleInfo:
    source = Path(path).read_text(encoding="utf-8", errors="replace")
    return parse_source(source, path=path, root=root)


def parse_source(source: str, *, path: Path | str, root: Path | str) -> ModuleInfo:
    path = Path(path)
    root = Path(root)
    module_name = module_name_of(path, root)
    info = ModuleInfo(path=str(path), module=module_name, lines=len(source.splitlines()))

    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        info.syntax_error = f"第 {exc.lineno} 行：{exc.msg}"
        return info

    info.docstring = ast.get_docstring(tree) or ""
    info.summary = parse_docstring(info.docstring).summary

    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                info.imports.append(
                    ImportInfo(module=alias.name, lineno=node.lineno, names=[alias.asname or alias.name])
                )
        elif isinstance(node, ast.ImportFrom):
            info.imports.append(
                ImportInfo(
                    module=node.module or "",
                    lineno=node.lineno,
                    names=[alias.asname or alias.name for alias in node.names],
                    is_from=True,
                    relative=bool(node.level),
                )
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            info.functions.append(_parse_function(node, is_method=False))
        elif isinstance(node, ast.ClassDef):
            info.classes.append(_parse_class(node))

    info.todos = _collect_todos(source)
    return info


def module_name_of(path: Path, root: Path) -> str:
    path = Path(path)
    root = Path(root)
    try:
        relative = path.relative_to(root)
    except ValueError:
        return path.stem
    parts = list(relative.with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) if parts else path.stem


def _annotation(node: ast.AST | None) -> str:
    if node is None:
        return ""
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - 老版本 Python 兜底
        return ""


def _parse_params(args: ast.arguments) -> list[ParamInfo]:
    params: list[ParamInfo] = []
    positional = list(args.posonlyargs) + list(args.args)
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    for arg, default in zip(positional, defaults):
        params.append(
            ParamInfo(
                name=arg.arg,
                annotation=_annotation(arg.annotation),
                default=_annotation(default) if default is not None else "",
                kind="positional",
            )
        )
    if args.vararg:
        params.append(ParamInfo(name=args.vararg.arg, annotation=_annotation(args.vararg.annotation),
                                kind="var_positional"))
    for arg, default in zip(args.kwonlyargs, args.kw_defaults):
        params.append(
            ParamInfo(
                name=arg.arg,
                annotation=_annotation(arg.annotation),
                default=_annotation(default) if default is not None else "",
                kind="keyword_only",
            )
        )
    if args.kwarg:
        params.append(ParamInfo(name=args.kwarg.arg, annotation=_annotation(args.kwarg.annotation),
                                kind="var_keyword"))
    return params


def _parse_function(node: ast.FunctionDef | ast.AsyncFunctionDef, *, is_method: bool) -> FunctionInfo:
    params = _parse_params(node.args)
    signature = f"{node.name}({', '.join(p.render() for p in params)})"
    returns = _annotation(node.returns)
    docstring = ast.get_docstring(node) or ""
    parsed = parse_docstring(docstring)

    return FunctionInfo(
        name=node.name,
        lineno=node.lineno,
        signature=signature,
        params=params,
        returns=returns,
        decorators=[_annotation(item) for item in node.decorator_list],
        is_async=isinstance(node, ast.AsyncFunctionDef),
        is_public=not node.name.startswith("_"),
        is_method=is_method,
        docstring=docstring,
        summary=parsed.summary,
        args_doc=parsed.args,
        returns_doc=parsed.returns,
        raises=parsed.raises,
        examples=parsed.examples,
        calls=_collect_calls(node),
        complexity=count_complexity(node),
        lines=(node.end_lineno or node.lineno) - node.lineno + 1,
    )


def _parse_class(node: ast.ClassDef) -> ClassInfo:
    docstring = ast.get_docstring(node) or ""
    parsed = parse_docstring(docstring)
    methods: list[FunctionInfo] = []
    attributes: list[tuple[str, str]] = []

    for child in node.body:
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods.append(_parse_function(child, is_method=True))
        elif isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name):
            attributes.append((child.target.id, _annotation(child.annotation)))
        elif isinstance(child, ast.Assign):
            for target in child.targets:
                if isinstance(target, ast.Name):
                    attributes.append((target.id, _annotation(child.value)))

    return ClassInfo(
        name=node.name,
        lineno=node.lineno,
        bases=[_annotation(item) for item in node.bases],
        decorators=[_annotation(item) for item in node.decorator_list],
        docstring=docstring,
        summary=parsed.summary,
        is_public=not node.name.startswith("_"),
        methods=methods,
        attributes=attributes,
        lines=(node.end_lineno or node.lineno) - node.lineno + 1,
    )


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parts = [node.attr]
        base: ast.AST = node.value
        while isinstance(base, ast.Attribute):
            parts.append(base.attr)
            base = base.value
        if isinstance(base, ast.Name):
            parts.append(base.id)
        return ".".join(reversed(parts))
    return ""


def _collect_calls(node: ast.AST) -> list[str]:
    found: list[str] = []
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            name = _call_name(child.func)
            if name and name not in found:
                found.append(name)
    return sorted(found)


def count_complexity(node: ast.AST) -> int:
    """粗糙的认知复杂度：1 + 分支/循环/异常等节点数。"""
    total = 1
    for child in ast.walk(node):
        if isinstance(child, COMPLEXITY_NODES):
            total += 1
    return total


def _collect_todos(source: str) -> list[TodoInfo]:
    todos: list[TodoInfo] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        match = TODO_PATTERN.search(line)
        if match:
            todos.append(TodoInfo(kind=match.group(1).upper(), text=match.group(2).strip(), lineno=lineno))
    return todos


# ====================================================================== 依赖分类
def classify_imports(imports: list[ImportInfo], root_module: str = "") -> dict[str, list[str]]:
    buckets: dict[str, list[str]] = {"标准库": [], "第三方": [], "项目内": []}
    for item in imports:
        if item.module == "__future__":  # 编译指令，不是真实依赖
            continue
        if item.relative:
            key = "项目内"
            name = (item.module or "").strip(".") or "(同一包)"
        else:
            top = (item.module or "").split(".")[0]
            if top in STDLIB_HINT:
                key = "标准库"
            elif root_module and top == root_module.split(".")[0]:
                key = "项目内"
            else:
                key = "第三方"
            name = item.module or "?"
        if name not in buckets[key]:
            buckets[key].append(name)
    return buckets


def call_edges(module: ModuleInfo) -> list[tuple[str, str]]:
    """模块内的调用关系（只保留本模块里定义的被调方，避免图太吵）。"""
    defined = {func.name for func in module.iter_functions()}
    defined |= {klass.name for klass in module.classes}
    edges: list[tuple[str, str]] = []
    for func in module.iter_functions():
        for call in func.calls:
            target = call.split(".")[-1] if "." in call else call
            if target in defined and target != func.name and (func.name, target) not in edges:
                edges.append((func.name, target))
    return edges
