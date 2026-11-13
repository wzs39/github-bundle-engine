"""合规闸: 仓库筛选 / Release 资产筛选 / LICENSE 保留校验.

三层判定:
  1. 关键词与 topic 黑名单 (策略书 5.3)
  2. 开源协议白名单 (策略书 5.1)
  3. 解包后 LICENSE 文件必须实际存在 (不是只信 API 字段)
"""
from __future__ import annotations

import json
import re
import tarfile
from pathlib import Path
from typing import Any

from .gh_client import Repo

_ZERO_WIDTH = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_CONTACT = re.compile(
    r"(微信号|微信号码|加微信|wechat\s*id|QQ号|qq号|加QQ|手机号|手机号码|二维码|扫码加群|加群|私聊|telegram|tg@)"
    r"|\b(?:wx|qq)\b|(?<![A-Za-z0-9])(1[3-9]\d{9})(?![A-Za-z0-9])"
    r"|([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})",
    re.IGNORECASE,
)
_FORCED_APP = re.compile(r"(必须下载|强制安装|不安装.*不发|下载.*App.*才能|注册.*才能领)")
_DECLARATION_RE = re.compile(r"所收费用仅为|遵循原项目开源协议|整理自\s*GitHub")


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as fh:
        return json.load(fh)


def _haystack(repo: Repo) -> str:
    return " ".join(
        [repo.full_name, repo.description, " ".join(repo.topics)]
    ).lower()


def term_hit(text: str, needle: str) -> bool:
    """黑名单命中判定. 短 ASCII 词用词边界匹配, 避免 "c2" 误伤 "abc2"/"c2c" 这类内容.

    中文等无词界语言直接子串匹配; 长 ASCII 词 (>=4 字符) 子串足够精确;
    短 ASCII 词 (<=3 字符) 要求两侧不是字母数字, 防止 "c2" 命中随机哈希/型号.
    """
    if not needle:
        return False
    if re.search(r"[\u4e00-\u9fff]", needle) or len(needle) > 3:
        return needle in text
    pattern = r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])"
    return re.search(pattern, text) is not None


def screen_repo(repo: Repo, cfg: dict[str, Any]) -> tuple[bool, str]:
    """返回 (是否收录, 原因). 任一红线命中即排除并记录具体原因."""
    # topic 分类先判: 显式声明的敏感分类优先于文本子串, 原因更精确.
    blocked_topics = {str(t).lower() for t in cfg.get("block_topics", [])}
    for topic in repo.topics:
        if topic.lower() in blocked_topics:
            return False, "命中 topic 黑名单: " + topic
    text = _haystack(repo)
    for term in cfg.get("block_terms", []):
        needle = str(term).lower()
        if needle and term_hit(text, needle):
            return False, "命中内容黑名单: " + str(term)
    allowed = {str(x) for x in cfg.get("allowed_license_spdx", [])}
    if allowed and repo.license_key not in allowed:
        return False, "开源协议不在白名单: " + repo.license_key
    if not repo.full_name or "/" not in repo.full_name:
        return False, "仓库标识异常"
    if int(repo.stars or 0) <= 0:
        return False, "Star 数异常"
    return True, "通过"


def select_release_assets(
    assets: list[dict[str, Any]], cfg: dict[str, Any]
) -> list[dict[str, Any]]:
    """只保留 Windows 可执行/安装包, 且单文件体积不超阈值."""
    exts = tuple(str(x).lower() for x in cfg.get("release_asset_extensions", []))
    ceiling = int(cfg.get("release_asset_max_mb", 300)) * 1024 * 1024
    picked: list[dict[str, Any]] = []
    for asset in assets:
        name = str(asset.get("name") or "")
        size = int(asset.get("size") or 0)
        url = str(asset.get("url") or "")
        if not url:
            continue
        if exts and not name.lower().endswith(exts):
            continue
        if size <= 0 or size > ceiling:
            continue
        if _CONTACT.search(name):
            continue
        picked.append(asset)
    return picked


def has_license(tar_path: str | Path, cfg: dict[str, Any]) -> tuple[bool, str]:
    """在归档条目里真实查找 LICENSE 文件, 防止 API 字段说谎."""
    names = {str(x).upper() for x in cfg.get("license_filenames", [])}
    try:
        with tarfile.open(tar_path, "r:*") as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                base = Path(member.name).name.upper()
                if base in names or base.startswith("LICENSE") or base.startswith("COPYING"):
                    return True, member.name
    except (tarfile.TarError, OSError) as exc:
        return False, "归档不可读: " + repr(exc)
    return False, "归档内未找到 LICENSE/COPYING"


def check_text(text: str) -> list[str]:
    """文案红线扫描. 返回问题列表, 空列表表示通过."""
    problems: list[str] = []
    if _ZERO_WIDTH.search(text):
        problems.append("含不可见字符 (零宽/软连字符/BOM)")
    if _CONTACT.search(text):
        problems.append("含站外引流联系方式 (微信/QQ/手机号/邮箱/二维码)")
    if _FORCED_APP.search(text):
        problems.append("含强制诱导拉新话术 (必须下载 App 才发货)")
    return problems


def check_declaration(text: str) -> list[str]:
    issues = check_text(text)
    if not _DECLARATION_RE.search(text):
        issues.append("缺少开源协议与整理服务费声明")
    return issues


def read_declaration(root: str | Path, cfg: dict[str, Any]) -> str:
    rel = str(cfg.get("declaration_text_file") or "")
    if not rel:
        return ""
    path = Path(root) / rel
    return path.read_text(encoding="utf-8").strip() if path.exists() else ""
