"""持久化：把订单存成 JSON 文件（演示用的极简实现）。"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from .models import Order, OrderLine


class OrderStore:
    """订单仓库。

    Args:
        path: JSON 文件路径。
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def save(self, order: Order) -> None:
        """把订单写入文件。

        Args:
            order: 要保存的订单。
        """
        payload = {
            "order_id": order.order_id,
            "lines": [
                {
                    "sku": line.sku,
                    "quantity": line.quantity,
                    "unit_price": str(line.unit_price),
                }
                for line in order.lines
            ],
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self, order_id: str) -> Order:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        lines = [
            OrderLine(item["sku"], item["quantity"], Decimal(item["unit_price"]))
            for item in data["lines"]
        ]
        return Order(order_id or data.get("order_id", ""), lines)
