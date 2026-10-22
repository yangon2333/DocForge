"""领域模型：订单与订单行。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class OrderLine:
    """一条订单明细。

    Args:
        sku: 商品编号。
        quantity: 数量，必须为正整数。
        unit_price: 单价（含税）。
    """

    sku: str
    quantity: int
    unit_price: Decimal

    def subtotal(self) -> Decimal:
        """计算该行的金额小计。

        Returns:
            数量乘以单价的结果。
        """
        return Decimal(self.quantity) * self.unit_price

    def is_valid(self) -> bool:
        return self.quantity > 0 and self.unit_price >= 0


@dataclass
class Order:
    """一张订单。

    Args:
        order_id: 订单号。
        lines: 订单明细列表。
    """

    order_id: str
    lines: list[OrderLine] = field(default_factory=list)

    def add_line(self, line: OrderLine) -> None:
        """追加一条明细。

        Args:
            line: 要追加的明细。
        """
        self.lines.append(line)

    def total_quantity(self) -> int:
        return sum(line.quantity for line in self.lines)
