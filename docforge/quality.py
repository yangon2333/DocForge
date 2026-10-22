"""文档质量：公开符号统计、缺口识别、覆盖率计算。

所有函数都作用在"已序列化的模块事实"（dict）上，因为工件要能落盘成 JSON，
阶段之间传的就是这份 dict，而不是内存里的 dataclass。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

BLOCKING = "blocking"
ADVISORY = "advisory"


@dataclass
class Gap:
    module: str
    qualname: str
    kind: str        # module-docstring / symbol-docstring / params-doc
    severity: str
    detail: str

    @property
    def key(self) -> str:
        return f"{self.module}:{self.qualname}"

    def to_dict(self) -> dict[str, str]:
        return {
            "module": self.module,
            "qualname": self.qualname,
            "kind": self.kind,
            "severity": self.severity,
            "detail": self.detail,
        }


def iter_symbols(module: dict[str, Any]) -> Iterable[dict[str, Any]]:
    """遍历一个模块里的公开符号（函数 + 类 + 公开方法）。"""
    for func in module.get("functions", []):
        if not func.get("is_public"):
            continue
        yield {
            "module": module["module"],
            "qualname": func["name"],
            "kind": "function",
            "lineno": func["lineno"],
            "params": [p["name"] for p in func.get("params", [])],
            "has_doc": bool(func.get("summary")),
            "summary": func.get("summary", ""),
            "args_doc": func.get("args_doc", {}),
            "complexity": func.get("complexity", 1),
        }

    for klass in module.get("classes", []):
        if klass.get("is_public"):
            yield {
                "module": module["module"],
                "qualname": klass["name"],
                "kind": "class",
                "lineno": klass["lineno"],
                "params": list(klass.get("bases", [])),
                "has_doc": bool(klass.get("summary")),
                "summary": klass.get("summary", ""),
                "args_doc": {},
                "complexity": 1,
            }
        for method in klass.get("methods", []):
            if not method.get("is_public"):
                continue
            yield {
                "module": module["module"],
                "qualname": f"{klass['name']}.{method['name']}",
                "kind": "method",
                "lineno": method["lineno"],
                "params": [
                    p["name"] for p in method.get("params", []) if p["name"] not in ("self", "cls")
                ],
                "has_doc": bool(method.get("summary")),
                "summary": method.get("summary", ""),
                "args_doc": method.get("args_doc", {}),
                "complexity": method.get("complexity", 1),
            }


def symbol_key(module: str, qualname: str) -> str:
    return f"{module}:{qualname}"


def find_gaps(modules: list[dict[str, Any]], patched: dict[str, Any] | None = None) -> list[Gap]:
    """找出文档缺口。patched 里已补写的符号不再算阻断。"""
    patched = patched or {}
    gaps: list[Gap] = []
    for module in modules:
        name = module["module"]
        if not module.get("summary"):
            gaps.append(
                Gap(
                    module=name,
                    qualname="(module)",
                    kind="module-docstring",
                    severity=ADVISORY,
                    detail="模块缺少 docstring，文档里只能列结构",
                )
            )
        for symbol in iter_symbols(module):
            key = symbol_key(symbol["module"], symbol["qualname"])
            filled = key in patched or bool(symbol["summary"])
            if not filled:
                gaps.append(
                    Gap(
                        module=name,
                        qualname=symbol["qualname"],
                        kind="symbol-docstring",
                        severity=BLOCKING,
                        detail=f"{symbol['kind']} 缺少 docstring（第 {symbol['lineno']} 行）",
                    )
                )
                continue
            missing_params = [p for p in symbol["params"] if p not in symbol["args_doc"]]
            if missing_params:
                gaps.append(
                    Gap(
                        module=name,
                        qualname=symbol["qualname"],
                        kind="params-doc",
                        severity=ADVISORY,
                        detail="参数未逐一说明：" + ", ".join(missing_params),
                    )
                )
    return gaps


def blocking_gaps(gaps: list[Gap]) -> list[Gap]:
    return [gap for gap in gaps if gap.severity == BLOCKING]


def coverage(modules: list[dict[str, Any]], patched: dict[str, Any] | None = None) -> dict[str, Any]:
    patched = patched or {}
    total = documented = auto = 0
    for module in modules:
        for symbol in iter_symbols(module):
            total += 1
            key = symbol_key(symbol["module"], symbol["qualname"])
            if symbol["summary"]:
                documented += 1
            elif key in patched:
                documented += 1
                auto += 1
    ratio = (documented / total) if total else 1.0
    return {
        "total": total,
        "documented": documented,
        "auto_filled": auto,
        "missing": total - documented,
        "ratio": round(ratio, 4),
        "percent": f"{ratio * 100:.1f}%",
    }


def stats(modules: list[dict[str, Any]], patched: dict[str, Any] | None = None,
          complexity_limit: int = 8) -> dict[str, Any]:
    classes = functions = methods = todos = 0
    high_complexity: list[dict[str, Any]] = []
    for module in modules:
        classes += len(module.get("classes", []))
        functions += len(module.get("functions", []))
        todos += len(module.get("todos", []))
        for klass in module.get("classes", []):
            methods += len(klass.get("methods", []))
        for symbol in iter_symbols(module):
            if symbol["complexity"] > complexity_limit:
                high_complexity.append(
                    {
                        "module": symbol["module"],
                        "qualname": symbol["qualname"],
                        "complexity": symbol["complexity"],
                        "lineno": symbol["lineno"],
                    }
                )
    high_complexity.sort(key=lambda item: item["complexity"], reverse=True)
    return {
        "modules": len(modules),
        "lines": sum(int(module.get("lines", 0)) for module in modules),
        "classes": classes,
        "functions": functions,
        "methods": methods,
        "todos": todos,
        "symbols": coverage(modules, patched)["total"],
        "coverage": coverage(modules, patched),
        "high_complexity": high_complexity,
        "syntax_errors": [
            {"module": module["module"], "error": module["syntax_error"]}
            for module in modules
            if module.get("syntax_error")
        ],
    }
