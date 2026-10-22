"""repair：为没有 docstring 的公开符号补写一句"结构性说明"。

注意边界：这里补的是**文档文字**，不改源码、不假装理解代码语义。
补写内容一律标注"自动补写，待人工确认"，并在质量报告里单列出来。
"""

from __future__ import annotations

from ..context import RunContext
from ..stage import Stage, StageResult

# 动词表：只覆盖常见的命名习惯，识别不出来就退回"处理「xxx」相关逻辑"
VERBS = {
    "get": "获取", "fetch": "获取", "load": "加载", "read": "读取", "save": "保存",
    "write": "写入", "dump": "导出", "export": "导出", "import": "导入", "parse": "解析",
    "build": "构建", "make": "创建", "create": "创建", "new": "新建", "init": "初始化",
    "update": "更新", "set": "设置", "delete": "删除", "remove": "移除", "clear": "清空",
    "check": "检查", "validate": "校验", "verify": "验证", "assert": "断言",
    "compute": "计算", "calc": "计算", "count": "统计", "sum": "汇总", "merge": "合并",
    "scan": "扫描", "collect": "收集", "gather": "收集", "normalize": "规范化",
    "format": "格式化", "render": "渲染", "print": "输出", "log": "记录",
    "run": "执行", "start": "启动", "stop": "停止", "close": "关闭", "reset": "重置",
    "is": "判断是否", "has": "判断是否存在", "can": "判断能否", "should": "判断是否应该",
    "to": "转换为", "from": "从…构造", "open": "打开", "process": "处理", "handle": "处理",
}


def infer_summary(qualname: str) -> str:
    """按命名习惯猜一句说明（明确标注是自动补写的）。"""
    name = qualname.rsplit(".", 1)[-1]
    words = [word for word in name.strip("_").split("_") if word]
    if not words:
        return "（自动补写：无法从命名推断，请人工补充）"

    verb = VERBS.get(words[0].lower(), "")
    if verb:
        rest = " ".join(words[1:]) or name
        return f"{verb}「{rest}」（自动补写，待人工确认）"
    return f"处理「{name}」相关逻辑（自动补写，待人工确认）"


class RepairStage(Stage):
    name = "repair"
    title = "自动补写缺失说明"

    def run(self, ctx: RunContext) -> StageResult:
        data = ctx.require("gaps")
        blocking = [item for item in data.get("items", []) if item.get("severity") == "blocking"]
        patched = dict(ctx.optional("patched", {}) or {})

        added: list[str] = []
        for gap in blocking:
            key = f"{gap['module']}:{gap['qualname']}"
            if key in patched:
                continue
            patched[key] = {
                "summary": infer_summary(gap["qualname"]),
                "params": {},
                "auto": True,
                "hint": gap.get("detail", ""),
            }
            added.append(gap["qualname"])

        if not added:
            ctx.note("本轮没有新增可补写的缺口")
            return StageResult(artifacts={"patched": patched}, message="没有可补写的缺口（本轮空转）")

        preview = "、".join(added[:6]) + (" 等" if len(added) > 6 else "")
        ctx.note(f"自动补写 {len(added)} 个符号：{preview}")
        return StageResult(
            artifacts={"patched": patched},
            message=f"补写 {len(added)} 个符号：{preview}",
        ).say("write", f"已补写 {len(added)} 个符号，请重新渲染并标注为自动补写")
