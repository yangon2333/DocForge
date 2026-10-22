"""计价规则：折扣与总价计算。"""

from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from .models import Order, OrderLine

DEFAULT_DISCOUNT = Decimal("0.0")
BULK_THRESHOLD = 10
BULK_DISCOUNT = Decimal("0.1")


def compute_total(order: Order) -> Decimal:
    """计算订单总额。

    Args:
        order: 待计算的订单。

    Returns:
        所有明细小计之和。

    Raises:
        ValueError: 订单里没有任何明细时。

    Examples:
        >>> compute_total(Order("A1", [OrderLine("S1", 2, Decimal("9.9"))]))
        Decimal('19.8')
    """
    if not order.lines:
        raise ValueError("订单没有明细，无法计算总额")
    return sum((line.subtotal() for line in order.lines), Decimal("0"))


def apply_discount(total: Decimal, quantity: int, discount: Decimal | None = None) -> Decimal:
    """按数量套用折扣。

    Args:
        total: 原始总价。
        quantity: 商品总件数。
        discount: 指定折扣率，默认按 bulk 规则自动选择。

    Returns:
        折后总价，保留两位小数。
    """
    # TODO: 折扣规则应做成可配置的，现在硬编码在函数体里
    rate = BULK_DISCOUNT if quantity >= BULK_THRESHOLD else DEFAULT_DISCOUNT
    if discount is not None:
        rate = discount
    return (total * (Decimal("1") - rate)).quantize(Decimal("0.01"))


def summarize(lines: Iterable[OrderLine]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line in lines:
        counts[line.sku] = counts.get(line.sku, 0) + line.quantity
    return counts
