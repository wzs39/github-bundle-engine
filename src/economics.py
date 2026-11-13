"""双引擎收益模型验算 (策略书 1 投入产出模型).

纯离线计算, 无网络. 输出稳定期单账号日收益区间与拆解.
用法: python scripts/economics.py [--orders N] [--links N]
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PRICE_BY_TIER = {
    "引流拉新款": 0.99,
    "走量款": 1.99,
    "利润款": 6.9,
    "高客单款": 9.9,
}
PAN_NEW_USER_CNY = (7.0, 12.0)
PAN_SAVE_CNY = (0.3, 0.5)


@dataclass
class Scenario:
    name: str
    effective_links: int
    orders_per_day: int
    avg_front_price: float
    pan_new_users: int
    pan_saves: int

    @property
    def front(self) -> float:
        return round(self.orders_per_day * self.avg_front_price, 2)

    @property
    def pan_low(self) -> float:
        return round(
            self.pan_new_users * PAN_NEW_USER_CNY[0]
            + self.pan_saves * PAN_SAVE_CNY[0],
            2,
        )

    @property
    def pan_high(self) -> float:
        return round(
            self.pan_new_users * PAN_NEW_USER_CNY[1]
            + self.pan_saves * PAN_SAVE_CNY[1],
            2,
        )

    def to_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["front_revenue"] = self.front
        d["pan_low"] = self.pan_low
        d["pan_high"] = self.pan_high
        d["total_low"] = round(self.front + self.pan_low, 2)
        d["total_high"] = round(self.front + self.pan_high, 2)
        return d


def baseline() -> list[Scenario]:
    return [
        Scenario("第一阶段·跑通闭环", 4, 1, 0.99, 1, 3),
        Scenario("第二阶段·20 链接", 20, 5, 3.50, 2, 18),
        Scenario("第二阶段·爆款", 22, 10, 4.20, 4, 30),
        Scenario("第三阶段·稳定", 20, 8, 3.80, 3, 26),
    ]


def blend_price(weights: dict[str, float] | None = None) -> float:
    w = weights or {"引流拉新款": 0.35, "走量款": 0.30, "利润款": 0.25, "高客单款": 0.10}
    total = sum(w.values()) or 1.0
    return round(sum(PRICE_BY_TIER[k] * v for k, v in w.items()) / total, 4)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="双引擎收益模型验算")
    p.add_argument("--orders", type=int, default=0, help="覆盖订单数, 追加一条自定义场景")
    p.add_argument("--links", type=int, default=20)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)

    rows = baseline()
    if args.orders:
        rows.append(
            Scenario(
                "自定义",
                args.links,
                args.orders,
                blend_price(),
                max(1, round(args.orders * 0.4)),
                max(1, round(args.orders * 2.6)),
            )
        )
    payload = {
        "schema": "github-bundle-engine/economics@1",
        "assumptions": {
            "pan_new_user_cny": list(PAN_NEW_USER_CNY),
            "pan_save_cny": list(PAN_SAVE_CNY),
            "price_by_tier": PRICE_BY_TIER,
            "blended_price": blend_price(),
            "settlement": "前端即时到账 / 网盘 T+1",
            "daily_time_minutes": 90,
            "strategy_target_cny": [40, 120],
        },
        "scenarios": [r.to_dict() for r in rows],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print("定价档位: " + json.dumps(PRICE_BY_TIER, ensure_ascii=False))
    print("加权均价: " + str(blend_price()) + " 元/单")
    print("网盘佣金: 拉新 " + str(PAN_NEW_USER_CNY) + " 元/人, 转存 " + str(PAN_SAVE_CNY) + " 元/次 (T+1)")
    print("")
    head = "{:<22} {:>5} {:>5} {:>9} {:>11} {:>11} {:>11}".format(
        "场景", "链接", "订单", "前端(元)", "网盘低-高", "合计低", "合计高"
    )
    print(head)
    print("-" * len(head))
    for r in rows:
        d = r.to_dict()
        print(
            "{:<22} {:>5} {:>5} {:>9.2f} {:>11} {:>11.2f} {:>11.2f}".format(
                d["name"],
                d["effective_links"],
                d["orders_per_day"],
                d["front_revenue"],
                str(d["pan_low"]) + "-" + str(d["pan_high"]),
                d["total_low"],
                d["total_high"],
            )
        )
    print("")
    print("策略书目标 40-120 元/日: 由 '第二阶段·爆款' 与 '第三阶段·稳定' 两档覆盖.")
    print("关键杠杆: 有效链接数 15-25, 拉新转化 >= 5%, 老买家每周追加更新触发二次转存.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
