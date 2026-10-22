"""示例包：一个极简的订单计价模块，用来演示 DocForge 的文档生成。

包里的 docstring 质量是刻意"不均匀"的：有的写得很规范（带 Args/Returns/Raises/Examples），
有的干脆没写——后者就是文档校验阶段的缺口，会触发补写回边。
"""

from .models import Order, OrderLine
from .pricing import apply_discount, compute_total, summarize
from .storage import OrderStore

__all__ = [
    "Order",
    "OrderLine",
    "OrderStore",
    "apply_discount",
    "compute_total",
    "summarize",
]
