"""上架排程: Day 6-7 冷启动 + 稳定期每日节奏 (策略书 4.1 / 4.2).

纯函数, 无网络无时间副作用 (时间由调用方显式传入).
硬约束:
  · 相邻两个上架槽间隔 >= listing_interval_minutes (默认 60)
  · 同一专题的相邻长尾词不重复, 全局轮转
  · 货架有效链接达 25 后新槽改为「擦亮/衍生」而非再新增
  · 产出可直接照着操作的 Markdown 时间表
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

DEFAULT_INTERVAL = 60
DEFAULT_PER_DAY = 2
LINK_MIN = 15
LINK_MAX = 25


def _topic_view(topic: dict[str, Any], manifest: dict[str, Any] | None) -> dict[str, Any]:
    mf = manifest or {}
    t = dict(mf.get("topic") or {})
    t.setdefault("id", topic.get("id", ""))
    t.setdefault("name", topic.get("name", ""))
    t.setdefault("price", topic.get("price", 0))
    t.setdefault("price_tier", topic.get("price_tier", ""))
    t.setdefault("selling_point", topic.get("selling_point", ""))
    t.setdefault("long_tail", topic.get("long_tail", []))
    t["folder"] = mf.get("folder", "")
    t["package_mb"] = mf.get("package_mb", 0)
    t["repo_count"] = mf.get("repo_count", 0)
    t["pan_bound"] = bool((mf.get("pan") or {}).get("share_url"))
    return t


def rotate_keywords(pool: list[str], seq: int, width: int = 3) -> list[str]:
    """从长尾词池轮转取 width 个, 每轮起始位前移一位, 同一专题各轮不重复.

    start = seq % n 而不是 seq*width % n: 后者在 n=4/width=3 时周期为 4,
    恰好与专题数相同, 会让同一专题每次都拿回同一组词.
    """
    if not pool:
        return []
    n = len(pool)
    width = min(width, n)
    start = seq % n
    return [str(pool[(start + i) % n]) for i in range(width)]


def build_schedule(
    topics: list[dict[str, Any]],
    manifests: dict[str, dict[str, Any]],
    start: datetime,
    days: int = 7,
    per_day: int = DEFAULT_PER_DAY,
    interval_minutes: int = DEFAULT_INTERVAL,
    existing_links: int = 0,
    stock_min: int = 50,
    stock_max: int = 99,
) -> dict[str, Any]:
    if interval_minutes < DEFAULT_INTERVAL:
        raise ValueError("上架间隔不得低于 60 分钟")
    if per_day < 1 or days < 1:
        raise ValueError("per_day / days 必须为正整数")
    views = [_topic_view(t, manifests.get(str(t.get("id", "")))) for t in topics]
    if not views:
        raise ValueError("没有可排程的专题, 先跑 build 或 selftest")

    slots: list[dict[str, Any]] = []
    links = existing_links
    seq = 0
    for day in range(days):
        day_date = (start + timedelta(days=day)).date().isoformat()
        for k in range(per_day):
            slot_time = start + timedelta(minutes=k * interval_minutes)
            view = views[seq % len(views)]
            topic_round = seq // len(views)
            keywords = rotate_keywords([str(x) for x in view["long_tail"]], topic_round)
            derivative = seq >= len(views) and bool(keywords)
            if links >= LINK_MAX and not derivative:
                action = "refresh"
                title = "[擦亮] " + str(view["name"])
                notes = "有效链接已达上限 25, 本槽改为全店擦亮 + 排查前 48 小时数据"
            elif links >= LINK_MAX and derivative:
                action = "derivative"
                title = "[衍生] " + str(view["name"]) + " " + (keywords[0] if keywords else "")
                notes = "换封面图 + 长尾词衍生链接; 不新增有效链接数, 达标后只做优化"
            else:
                action = "new"
                title = str(view["name"]) + " " + " ".join(keywords[:2])
                links += 1
                notes = "新品上架; 库存 " + str(stock_min) + "-" + str(stock_max)
            if not view["pan_bound"]:
                notes += "; [待补] 该专题尚未 bind-pan, 上架前回填推广链接"
            slots.append(
                {
                    "seq": seq + 1,
                    "date": day_date,
                    "time": slot_time.strftime("%H:%M"),
                    "iso_local": slot_time.isoformat(),
                    "topic_id": view["id"],
                    "topic_name": view["name"],
                    "action": action,
                    "title": title[:60],
                    "price": view["price"],
                    "keywords": keywords,
                    "cover": "目录截图 + 痛点大字: " + str(view["selling_point"]),
                    "stock": [stock_min, stock_max],
                    "interval_minutes": interval_minutes,
                    "gap_ok": True,
                    "effective_links_after": links,
                    "notes": notes,
                }
            )
            seq += 1

    return {
        "schema": "github-bundle-engine/schedule@1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window": {
            "start": start.isoformat(),
            "days": days,
            "per_day": per_day,
            "interval_minutes": interval_minutes,
            "slots": len(slots),
        },
        "shelf": {
            "existing_links": existing_links,
            "final_links": links,
            "target_min": LINK_MIN,
            "target_max": LINK_MAX,
            "in_target": LINK_MIN <= links <= LINK_MAX,
        },
        "daily_sop": {
            "first_25min": "运行 build 新增 1 个细分专题包并上传网盘, 保持有效链接 15-25",
            "middle_35min": "全店擦亮; 曝光<100 且零想要的链接删除重发; 爆款做 1-2 个长尾衍生",
            "last_30min": "回复配置咨询并补进 01 文件; 核对 T+1 拉新/转存; 淘汰转化率<5%的链接",
        },
        "retire_rule": "上架 48 小时曝光 < 100 且零想要 -> 删除重发, 换主图与长尾词",
        "slots": slots,
    }


def render_schedule_md(schedule: dict[str, Any]) -> str:
    w = schedule["window"]
    s = schedule["shelf"]
    lines = [
        "# 闲鱼上架排程",
        "",
        "起始: " + str(w["start"]) + " | " + str(w["days"]) + " 天 | 每天 " + str(w["per_day"]) + " 条 | 间隔 " + str(w["interval_minutes"]) + " 分钟",
        "货架: 起始 " + str(s["existing_links"]) + " -> 结束 " + str(s["final_links"]) + " (目标 " + str(s["target_min"]) + "-" + str(s["target_max"]) + ")",
        "",
        "| # | 日期 | 时间 | 动作 | 专题 | 标题/长尾 | 价格 | 链接数 | 备注 |",
        "| ---: | --- | --- | --- | --- | --- | ---: | ---: | --- |",
    ]
    for slot in schedule["slots"]:
        lines.append(
            "| " + str(slot["seq"])
            + " | " + str(slot["date"])
            + " | " + str(slot["time"])
            + " | " + str(slot["action"])
            + " | " + str(slot["topic_id"])
            + " | " + str(slot["title"]).replace("|", "/")
            + " | " + str(slot["price"])
            + " | " + str(slot["effective_links_after"])
            + " | " + str(slot["notes"]).replace("|", "/")
            + " |"
        )
    lines += [
        "",
        "## 每日 90 分钟 SOP",
        "",
        "- 前 25 分钟: " + str(schedule["daily_sop"]["first_25min"]),
        "- 中间 35 分钟: " + str(schedule["daily_sop"]["middle_35min"]),
        "- 最后 30 分钟: " + str(schedule["daily_sop"]["last_30min"]),
        "",
        "## 淘汰线",
        "",
        schedule["retire_rule"],
        "",
        "发货前逐条跑 `python -m src.cli verify --out OUTPUT_DIR`; 未 bind-pan 的槽先补推广链接.",
        "",
    ]
    return "\n".join(lines)
