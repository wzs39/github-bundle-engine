"""网盘推广链接回填 (策略书 2.1 / 4.1 / 5.2).

把已报备渠道生成的分享链接与提取码写进 _manifest.json 的 pan 段,
重生成 auto_reply.txt, 并在写回前做红线扫描:
  · 分享链只允许 http(s), 且不得含联系方式型参数
  · 提取码不得含联系方式 / 强制诱导话术
  · 生成的发货文案必须过 check_text
"""
from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .compliance import check_text
from .downloader import write_json_atomic
from .listing import render_auto_reply

_PLACEHOLDER = re.compile(r"^\[[A-Z0-9_]+\]$")
_CONTACT_QUERY = re.compile(r"(wx|qq|wechat|phone|mobile|tel|qrcode)", re.IGNORECASE)


def validate_share_url(url: str) -> list[str]:
    problems: list[str] = []
    if not url:
        problems.append("分享链接为空")
        return problems
    if _PLACEHOLDER.match(url):
        problems.append("分享链接仍是占位符, 需填已报备 UID 生成的真实推广链")
        return problems
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        problems.append("分享链接必须是完整 http(s) URL")
    for key, _value in urllib.parse.parse_qsl(parsed.query, keep_blank_values=True):
        if _CONTACT_QUERY.search(key):
            problems.append("分享链接参数疑似联系方式: " + key)
    problems.extend("分享链接: " + x for x in check_text(url))
    return problems


def validate_extract_code(code: str) -> list[str]:
    if not code:
        return ["提取码为空"]
    if _PLACEHOLDER.match(code):
        return ["提取码仍是占位符"]
    return ["提取码: " + x for x in check_text(code)]


def find_manifests(root: str | Path, topic_id: str = "") -> dict[str, Path]:
    out: dict[str, Path] = {}
    for path in sorted(Path(root).glob("2026持续更新_*合集/_manifest.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        tid = str((data.get("topic") or {}).get("id") or "")
        if tid and (not topic_id or tid == topic_id):
            out[tid] = path
    return out


def bind(
    root: str | Path,
    topic_id: str,
    share_url: str,
    extract_code: str,
    promote_uid: str = "",
    channel_reported: bool = True,
) -> dict[str, Any]:
    problems = validate_share_url(share_url) + validate_extract_code(extract_code)
    if problems:
        raise ValueError("; ".join(problems))
    manifests = find_manifests(root, topic_id)
    if topic_id not in manifests:
        raise ValueError("未找到专题 " + topic_id + " 的 _manifest.json, 先跑 build")

    mf_path = manifests[topic_id]
    data = json.loads(mf_path.read_text(encoding="utf-8"))
    topic_view = dict(data.get("topic") or {})
    topic_view.setdefault("id", topic_id)
    topic_view.setdefault("name", topic_view.get("name") or topic_id)

    reply_text = render_auto_reply(topic_view, share_url, extract_code)
    reply_issues = check_text(reply_text)
    if reply_issues:
        raise ValueError("自动发货文案红线: " + "; ".join(reply_issues))

    pan = dict(data.get("pan") or {})
    pan.update(
        {
            "provider": str(pan.get("provider") or "quark"),
            "promote_uid_env": "PAN_PROMOTE_UID",
            "promote_uid": promote_uid,
            "share_url": share_url,
            "extract_code": extract_code,
            "channel_reported": bool(channel_reported),
            "bound_at": datetime.now(timezone.utc).isoformat(),
            "settlement": "T+1",
        }
    )
    data["pan"] = pan
    write_json_atomic(mf_path, data)

    reply_path = Path(root) / "listings" / topic_id / "auto_reply.txt"
    reply_path.parent.mkdir(parents=True, exist_ok=True)
    reply_path.write_text(reply_text, encoding="utf-8", newline="\n")

    return {
        "topic_id": topic_id,
        "manifest": str(mf_path),
        "auto_reply": str(reply_path),
        "share_url": share_url,
        "extract_code": extract_code,
        "channel_reported": bool(channel_reported),
        "clean": True,
    }
