"""网盘盈利闭环: 日报核算 -> 多日累计 -> 阶段判定 -> 目标差距 -> 预测.

纯离线. 数据来源是 reports/daily_<date>.json (由 report / selftest 产出).
盈利链路里只有两件事引擎做不了: 渠道报备生成真实推广链 与 网盘上传,
其余核算 / 归因 / 目标追踪全部自动化。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .economics import (
    PAN_NEW_USER_CNY,
    PAN_SAVE_CNY,
    Scenario,
    baseline,
    blend_price,
)

REPORT_SCHEMA = "github-bundle-engine/revenue@1"
# 策略书阶段: 链接数与阶段名 (ops-sop 稳定运营期)
STAGES = [
    (0, "第一阶段·跑通闭环"),
    (15, "第二阶段·20 链接"),
    (20, "第二阶段·爆款"),
]
TARGET_LOW = 40.0
TARGET_HIGH = 120.0


def _stage_for_links(links: int) -> str:
    name = STAGES[0][1]
    for floor, stage_name in STAGES:
        if links >= floor:
            name = stage_name
    return name


def profit_from_report(report: dict[str, Any]) -> dict[str, Any]:
    """单日核算: 前端即时到账 + 网盘 T+1 佣金, 并用佣金区间做交叉校验."""
    shelf = report.get("shelf") or {}
    xianyu = report.get("xianyu") or {}
    pan = report.get("pan") or {}
    links = int(shelf.get("effective_links") or 0)
    new_users = int(pan.get("new_users") or 0)
    saves = int(pan.get("saves") or 0)
    commission = float(pan.get("commission_cny") or 0.0)
    front = float(xianyu.get("front_revenue_cny") or 0.0)
    expected_low = round(new_users * PAN_NEW_USER_CNY[0] + saves * PAN_SAVE_CNY[0], 2)
    expected_high = round(new_users * PAN_NEW_USER_CNY[1] + saves * PAN_SAVE_CNY[1], 2)
    plausible = bool(expected_high <= 0 or (expected_low - 0.01) <= commission <= (expected_high + 0.01))
    total = round(front + commission, 2)
    gap_low = round(TARGET_LOW - total, 2)
    return {
        "date": str(report.get("date") or ""),
        "effective_links": links,
        "stage": _stage_for_links(links),
        "orders": int(xianyu.get("orders") or 0),
        "front_revenue_cny": round(front, 2),
        "pan_new_users": new_users,
        "pan_saves": saves,
        "pan_commission_cny": round(commission, 2),
        "pan_commission_expected_range": [expected_low, expected_high],
        "commission_plausible": plausible,
        "total_revenue_cny": total,
        "target_low_cny": TARGET_LOW,
        "target_high_cny": TARGET_HIGH,
        "gap_to_target_low_cny": gap_low,
        "hit_target_low": total >= TARGET_LOW,
        "hit_target_high": total >= TARGET_HIGH,
    }


def cumulative(reports_dir: str | Path) -> dict[str, Any]:
    """扫描 reports/daily_*.json 做多日累计与阶段判定. 无日报时返回空结构."""
    paths = sorted(Path(reports_dir).glob("daily_*.json"))
    dailies: list[dict[str, Any]] = []
    for path in paths:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if str(data.get("schema") or "") != "github-bundle-engine/daily-report@1":
            continue
        dailies.append(profit_from_report(data))
    if not dailies:
        return {
            "schema": REPORT_SCHEMA,
            "days": 0,
            "note": "还没有日报, 先跑 report --orders N --pan-new N 记录当天数据",
        }
    total_front = round(sum(d["front_revenue_cny"] for d in dailies), 2)
    total_commission = round(sum(d["pan_commission_cny"] for d in dailies), 2)
    total_new = sum(d["pan_new_users"] for d in dailies)
    total_saves = sum(d["pan_saves"] for d in dailies)
    total_orders = sum(d["orders"] for d in dailies)
    grand = round(total_front + total_commission, 2)
    days = len(dailies)
    latest = dailies[-1]
    best = max(dailies, key=lambda d: d["total_revenue_cny"])
    daily_avg = round(grand / days, 2)
    return {
        "schema": REPORT_SCHEMA,
        "days": days,
        "first_date": dailies[0]["date"],
        "last_date": latest["date"],
        "latest_stage": latest["stage"],
        "effective_links_latest": latest["effective_links"],
        "orders_total": total_orders,
        "front_revenue_total_cny": total_front,
        "pan_new_users_total": total_new,
        "pan_saves_total": total_saves,
        "pan_commission_total_cny": total_commission,
        "pan_share_of_revenue": round(
            (total_commission / grand * 100.0) if grand else 0.0, 1
        ),
        "total_revenue_cny": grand,
        "daily_avg_cny": daily_avg,
        "best_day": {"date": best["date"], "total_revenue_cny": best["total_revenue_cny"]},
        "target_low_cny": TARGET_LOW,
        "target_high_cny": TARGET_HIGH,
        "daily_gap_to_target_low_cny": round(TARGET_LOW - daily_avg, 2),
        "daily_avg_hit_target_low": daily_avg >= TARGET_LOW,
        "daily_avg_hit_target_high": daily_avg >= TARGET_HIGH,
        "dailies": dailies,
    }


def projection(effective_links: int, orders: int) -> dict[str, Any]:
    """按当前链接数与订单数给收益预测区间 (复用 economics 场景模型)."""
    price = blend_price()
    custom = Scenario(
        "当前运营外推",
        effective_links,
        max(orders, 0),
        price,
        max(1, round(orders * 0.4)) if orders else 1,
        max(1, round(orders * 2.6)) if orders else 3,
    )
    rows = baseline() + [custom]
    return {
        "schema": "github-bundle-engine/revenue-projection@1",
        "blended_price_cny": price,
        "assumptions": {
            "pan_new_user_cny": list(PAN_NEW_USER_CNY),
            "pan_save_cny": list(PAN_SAVE_CNY),
            "settlement": "前端即时到账 / 网盘 T+1",
        },
        "scenarios": [r.to_dict() for r in rows],
    }


def summary_line(cum: dict[str, Any]) -> str:
    """daily 收尾的一行盈利状态."""
    if not cum.get("days"):
        return str(cum.get("note") or "暂无日报")
    return (
        "盈利状态: 累计 " + str(cum["days"]) + " 天 "
        + str(cum["total_revenue_cny"]) + " 元 (前端 "
        + str(cum["front_revenue_total_cny"]) + " + 网盘佣金 "
        + str(cum["pan_commission_total_cny"]) + "), 日均 "
        + str(cum["daily_avg_cny"]) + " / 目标 " + str(TARGET_LOW) + "-"
        + str(TARGET_HIGH) + ", 当前阶段 " + str(cum["latest_stage"])
    )


def render_markdown(cum: dict[str, Any], proj: dict[str, Any] | None = None) -> str:
    lines = ["# 盈利核算与预测", ""]
    if not cum.get("days"):
        lines.append(str(cum.get("note") or "暂无日报"))
        return "\n".join(lines)
    lines += [
        "- 统计区间: " + str(cum["first_date"]) + " ~ " + str(cum["last_date"])
        + " (" + str(cum["days"]) + " 天)",
        "- 累计营收: **" + str(cum["total_revenue_cny"]) + " 元** = 前端 "
        + str(cum["front_revenue_total_cny"]) + " (订单 "
        + str(cum["orders_total"]) + " 单) + 网盘佣金 "
        + str(cum["pan_commission_total_cny"]) + " (拉新 "
        + str(cum["pan_new_users_total"]) + " / 转存 "
        + str(cum["pan_saves_total"]) + ")",
        "- 网盘收入占比: " + str(cum["pan_share_of_revenue"]) + "%",
        "- 日均: " + str(cum["daily_avg_cny"]) + " 元 / 目标 40-120 元, 差口 "
        + str(cum["daily_gap_to_target_low_cny"]) + " 元",
        "- 当前阶段: " + str(cum["latest_stage"]) + " (有效链接 "
        + str(cum["effective_links_latest"]) + " 个, 目标 15-25)",
        "- 最好一天: " + str(cum["best_day"]["date"]) + " "
        + str(cum["best_day"]["total_revenue_cny"]) + " 元",
        "",
        "| 日期 | 链接 | 订单 | 前端(元) | 网盘佣金(元) | 合计(元) | 达标 |",
        "|---|---|---|---|---|---|---|",
    ]
    for d in cum["dailies"]:
        lines.append(
            "| " + str(d["date"]) + " | " + str(d["effective_links"]) + " | "
            + str(d["orders"]) + " | " + str(d["front_revenue_cny"]) + " | "
            + str(d["pan_commission_cny"]) + " | " + str(d["total_revenue_cny"])
            + " | " + ("✓" if d["hit_target_low"] else "✗") + " |"
        )
    if proj:
        lines += ["", "## 预测 (按当前链接与订单外推)", ""]
        for row in proj.get("scenarios") or []:
            lines.append(
                "- " + str(row["name"]) + ": 链接 " + str(row["effective_links"])
                + ", 订单 " + str(row["orders_per_day"]) + " -> 合计 "
                + str(row["total_low"]) + " - " + str(row["total_high"]) + " 元/日"
            )
    return "\n".join(lines)
