"""闲鱼上架物料 + 自动发货话术 + 数据复盘模板.

策略书 4.2 / 5.2:
  标题带长尾词, 主图用目录截图 + 痛点大字, 库存 50-99, 间隔 >= 60 分钟.
  自动发货文案 3 秒内发出, 温和引导转存, 不出现联系方式与强制 App 话术.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .compliance import check_text

BANNED_IN_REPLY = ("微信号", "QQ号", "手机号", "二维码", "加我", "私聊", "必须下载")


def _assert_clean(label: str, text: str) -> None:
    issues = check_text(text)
    if issues:
        raise ValueError(label + " 文案红线: " + "; ".join(issues))
    for word in BANNED_IN_REPLY:
        if word in text:
            raise ValueError(label + " 含禁用词: " + word)


def render_title(topic: dict[str, Any]) -> str:
    base = "GitHub精选【" + str(topic["name"]) + "】合集"
    tail = " " + " ".join(str(x) for x in topic.get("long_tail", [])[:3])
    title = base + tail + " 中文说明 持续更新"
    return title[:60]


def render_detail(topic: dict[str, Any], manifest: dict[str, Any], declaration: str) -> str:
    lines = [
        "【" + str(topic["name"]) + "】GitHub 高星开源项目精选合集 · 2026 持续更新",
        "",
        "定价: " + str(topic["price"]) + " 元 (" + str(topic["price_tier"]) + ")",
        "收录: " + str(manifest.get("repo_count", 0)) + " 个高星仓库源码, 全部完整保留 LICENSE",
        "体积: 约 " + str(manifest.get("package_mb", 0)) + " MB (解压后多级目录, 不用死压缩包)",
        "",
        "解决什么问题",
    ]
    intro = [str(p) for p in topic.get("intro", [])]
    if intro:
        for para in intro[:2]:
            lines.append("· " + para)
    else:
        lines.append("· GitHub 国内直连不稳定, 找全一套同场景工具要翻半天")
        lines.append("· 全英文 README 读不动, 环境依赖配不起来")
        lines.append("· 缺按业务场景归好类的中文清单, 不知道哪个项目能直接用")
    lines += [
        "",
        "你会拿到",
        "00_项目清单与中文简介说明.md   含 Star 数 / 功能摘要 / 原仓库 URL / 协议声明",
        "01_新手环境配置与国内镜像加速.txt  Python / Node / Maven 国内源命令",
        "02_Windows免安装可执行程序包/  已提取的官方 Release 安装包",
        "03_精选开源项目源码合集/       按编号排列的源码, 原 LICENSE 一字不动",
        "",
        "适合: " + str(topic["audience"]),
        "卖点: " + str(topic["selling_point"]),
        "",
        "交付方式: 付款后自动发送网盘链接与提取码, 秒发不用等.",
        "资源已整理存入网盘, 因开源文件夹较大, 建议保存至个人网盘后按需下载,",
        "内附中文部署清单. 文件夹每周追加新项目, 老买家可再次转存.",
        "",
        "— 合规声明 —",
        declaration,
        "",
        "说明: 本商品为虚拟资料整理服务, 交付后请当场核对目录; 有环境配置问题可在订单内留言.",
        "不做站外沟通, 不提供代装代部署, 不承诺任何项目永久可用.",
        "",
    ]
    text = "\n".join(lines)
    _assert_clean("详情页", text)
    return text


def render_auto_reply(topic: dict[str, Any], share_url: str, extract_code: str) -> str:
    text = "\n".join(
        [
            "感谢购买【" + str(topic["name"]) + "】, 资源已自动发货:",
            "",
            "链接: " + (share_url or "[PAN_SHARE_URL]"),
            "提取码: " + (extract_code or "[PAN_EXTRACT_CODE]"),
            "",
            "资源已整理存入网盘, 因开源文件夹较大, 建议保存至个人网盘后按需下载,",
            "内附中文部署清单(00 项目清单 / 01 环境配置与国内镜像加速).",
            "打开 00_项目清单与中文简介说明.md 可按编号找项目;",
            "配环境请先看 01_新手环境配置与国内镜像加速.txt.",
            "文件夹会每周追加新项目, 需要时回来转存即可.",
            "",
            "如链接失效或目录对不上, 直接在订单内留言, 会补发新的分享链接.",
            "",
        ]
    )
    _assert_clean("自动发货", text)
    return text


def render_listing_plan(topic: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    return {
        "topic_id": topic["id"],
        "title": render_title(topic),
        "price": topic["price"],
        "stock_min": 50,
        "stock_max": 99,
        "listing_interval_minutes": 60,
        "main_image": "目录截图 + 痛点大字: " + str(topic["selling_point"]),
        "long_tail_keywords": list(topic.get("long_tail", [])),
        "derivative_links": [
            "同专题换封面图 + 长尾词: " + str(k) for k in topic.get("long_tail", [])[:2]
        ],
        "retire_rule": "上架 48 小时曝光 < 100 且零想要 -> 删除重发, 换主图与长尾词",
        "retire_rule_pan": "服务商后台拉新转化率 < 5% -> 淘汰该推广链接",
        "folder": manifest.get("folder", ""),
        "declared_price_tier": topic["price_tier"],
    }


def render_daily_report(
    date: str,
    link_count: int,
    exposures: int,
    wants: int,
    orders: int,
    front_revenue: float,
    pan_new_users: int,
    pan_saves: int,
    pan_commission: float,
    notes: list[str] | None = None,
) -> dict[str, Any]:
    conversion = (orders / exposures) if exposures else 0.0
    return {
        "schema": "github-bundle-engine/daily-report@1",
        "date": date,
        "shelf": {
            "effective_links": link_count,
            "target_min": 15,
            "target_max": 25,
            "in_target": 15 <= link_count <= 25,
        },
        "xianyu": {
            "exposures": exposures,
            "wants": wants,
            "orders": orders,
            "conversion_rate": round(conversion, 4),
            "front_revenue_cny": round(front_revenue, 2),
        },
        "pan": {
            "new_users": pan_new_users,
            "saves": pan_saves,
            "commission_cny": round(pan_commission, 2),
            "settlement": "T+1",
        },
        "total_revenue_cny": round(front_revenue + pan_commission, 2),
        "actions": notes or [
            "全店擦亮",
            "删除曝光<100且零想要的链接并重发",
            "爆款链接制作 1-2 个长尾衍生链接",
            "高频咨询补进 01_新手环境配置与国内镜像加速.txt",
            "核对服务商后台 T+1 数据, 淘汰转化率<5%的链接",
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def save_listing_bundle(
    root: str | Path,
    topic: dict[str, Any],
    manifest: dict[str, Any],
    declaration: str,
    share_url: str = "",
    extract_code: str = "",
) -> dict[str, Any]:
    base = Path(root) / "listings" / str(topic["id"])
    base.mkdir(parents=True, exist_ok=True)
    detail = render_detail(topic, manifest, declaration)
    reply = render_auto_reply(topic, share_url, extract_code)
    plan = render_listing_plan(topic, manifest)
    (base / "xianyu_detail.md").write_text(detail, encoding="utf-8", newline="\n")
    (base / "auto_reply.txt").write_text(reply, encoding="utf-8", newline="\n")
    (base / "listing_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "detail": str(base / "xianyu_detail.md"),
        "auto_reply": str(base / "auto_reply.txt"),
        "plan": str(base / "listing_plan.json"),
        "clean": True,
    }
