"""热点聚合发现层: 读热门总结站 -> 关键词归属 -> 专题刷新建议.

零第三方依赖 (urllib + re + json + html). 设计原则:

- 每个源独立失败: 单站改版 / 挂掉只降级为空结果 + warning, 不阻塞 daily 流水线;
- 候选仓库与建议词在发现阶段就过文案红线, 脏词进不了 topics.json 与任何上架物料;
- --apply 只动 search_tags / long_tail / trend_repos 三个字段,
  价格 / 受众 / 场景导语永不自动改 (那些要过人工)。

线格式参考 docs/IDLE-mod... 无关; 本模块只消费公开聚合站点,
解析失败时把原始响应留档到 OUTPUT_DIR/cache/trends/ 便于排查改版。
"""
from __future__ import annotations

import html as html_mod
import json
import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .compliance import check_text, term_hit
from .downloader import write_json_atomic

REPORT_SCHEMA = "github-bundle-engine/trends@1"


class TrendsError(RuntimeError):
    """单个热点源的可复现失败, 带源 id 与原因."""


@dataclass
class HotItem:
    """一条热点记录. github_trending 源带 repo 字段, 其余源 repo 为空."""

    source_id: str
    title: str
    heat: int = 0
    url: str = ""
    extra: str = ""
    repo: str = ""
    weight: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source_id,
            "title": self.title,
            "heat": self.heat,
            "url": self.url,
            "extra": self.extra,
            "repo": self.repo,
        }


# ---------------------------------------------------------------------------
# 抓取: 限速 + 退避, 单源耗尽抛 TrendsError
# ---------------------------------------------------------------------------

_LAST_CALL = 0.0


def _throttle(min_interval: float) -> None:
    global _LAST_CALL
    gap = time.monotonic() - _LAST_CALL
    if gap < min_interval:
        time.sleep(min_interval - gap)
    _LAST_CALL = time.monotonic()


def fetch_bytes(
    url: str,
    *,
    user_agent: str,
    timeout: float,
    retries: int,
    min_interval: float,
    extra_headers: dict[str, str] | None = None,
) -> bytes:
    headers = {
        "User-Agent": user_agent,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.6",
    }
    if extra_headers:
        headers.update({str(k): str(v) for k, v in extra_headers.items() if v})
    last = "unknown"
    for attempt in range(max(1, retries)):
        _throttle(min_interval)
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            last = "HTTP " + str(exc.code)
            if exc.code in (403, 429, 502, 503):
                time.sleep(min(2.0 * (attempt + 1), 10.0))
                continue
            break
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = repr(exc)
            time.sleep(min(2.0 * (attempt + 1), 10.0))
    raise TrendsError(last + " on " + url)


# ---------------------------------------------------------------------------
# 解析器: github trending HTML + 通用 JSON API 字段映射
# ---------------------------------------------------------------------------

_ROW_SPLIT = re.compile(r'<article class="Box-row">')
_REPO_RE = re.compile(r'href="/([\w.-]+/[\w.-]+)/stargazers"')
_DESC_RE = re.compile(r'<p class="col-9[^"]*"[^>]*>(.*?)</p>', re.S)
_LANG_RE = re.compile(r'itemprop="programmingLanguage">\s*([^<]+?)\s*<')
_TODAY_RE = re.compile(r'([\d,]+)\s*stars\s*today')
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(fragment: str) -> str:
    return html_mod.unescape(_TAG_RE.sub("", fragment)).strip()


def parse_github_trending(html_text: str, source_id: str) -> list[HotItem]:
    """解析 github.com/trending 页面. 行结构变化时逐行降级, 不抛异常."""
    items: list[HotItem] = []
    for chunk in _ROW_SPLIT.split(html_text)[1:]:
        match = _REPO_RE.search(chunk)
        if not match:
            continue
        repo = match.group(1).strip("/")
        heat = 0
        hm = _TODAY_RE.search(chunk)
        if hm:
            heat = int(hm.group(1).replace(",", "") or 0)
        desc = ""
        dm = _DESC_RE.search(chunk)
        if dm:
            desc = _clean(dm.group(1))[:300]
        lang = ""
        lm = _LANG_RE.search(chunk)
        if lm:
            lang = lm.group(1).strip()
        items.append(
            HotItem(
                source_id=source_id,
                title=repo,
                heat=heat,
                url="https://github.com/" + repo,
                extra=(" ".join(x for x in (desc, "[" + lang + "]" if lang else "") if x)),
                repo=repo,
            )
        )
    return items


def _walk(data: Any, dotted: str) -> Any:
    cur = data
    for part in str(dotted).split("."):
        if isinstance(cur, list):
            try:
                cur = cur[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(cur, dict):
            if part not in cur:
                return None
            cur = cur[part]
        else:
            return None
    return cur


def _to_int(raw: Any) -> int:
    if raw is None:
        return 0
    if isinstance(raw, bool):
        return int(raw)
    if isinstance(raw, (int, float)):
        return int(raw)
    text = str(raw).strip()
    # 中文数量级: "521万" -> 5210000, "1.2亿" -> 120000000
    scale = 1
    if text.endswith("亿"):
        scale, text = 100000000, text[:-1]
    elif text.endswith("万"):
        scale, text = 10000, text[:-1]
    digits = re.sub(r"[^\d.]", "", text)
    if not digits:
        return 0
    try:
        return int(float(digits) * scale)
    except ValueError:
        return 0


def parse_json_api(data: Any, spec: dict[str, Any], source_id: str) -> list[HotItem]:
    """通用 JSON 源: 按 item_path 取列表, 按字段映射取标题/热度/链接."""
    rows = _walk(data, str(spec.get("item_path") or ""))
    if not isinstance(rows, list):
        raise TrendsError(source_id + ": item_path 未取到列表")
    title_path = str(spec.get("title_field") or "title")
    heat_path = str(spec.get("heat_field") or "")
    url_path = str(spec.get("url_field") or "")
    extra_path = str(spec.get("extra_field") or "")
    prefix = str(spec.get("url_prefix") or "")
    max_items = int(spec.get("max_items") or 60)
    items: list[HotItem] = []
    for row in rows[:max_items]:
        title = _walk(row, title_path)
        title = str(title).strip() if title is not None else ""
        if not title:
            continue
        url_val = _walk(row, url_path) if url_path else None
        url = (prefix + str(url_val)) if (url_val and prefix) else str(url_val or "")
        extra_val = _walk(row, extra_path) if extra_path else None
        items.append(
            HotItem(
                source_id=source_id,
                title=title[:200],
                heat=_to_int(_walk(row, heat_path) if heat_path else 0),
                url=url[:400],
                extra=(str(extra_val).strip()[:300] if extra_val else ""),
            )
        )
    return items


# ---------------------------------------------------------------------------
# 归属与评分: 关键词子串命中, 源权重 x 热度加成
# ---------------------------------------------------------------------------

def item_haystack(item: HotItem) -> str:
    return (item.title + " " + item.extra).lower()


def parse_github_search(data: Any, source_id: str) -> list[HotItem]:
    """GitHub Search API 结果: full_name / description / stars / topics 全保留.

    教育类垂直 (考研/高考/英语) 的稳定信号源: 官方 API, 不受聚合站改版影响.
    """
    if isinstance(data, dict) and data.get("items") is None:
        raise TrendsError(source_id + ": 无 items 字段 (检查 q 参数与限流)")
    rows = data.get("items") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise TrendsError(source_id + ": 响应不是搜索结果")
    items: list[HotItem] = []
    for row in rows[: int((data or {}).get("_max_items") or 15)]:
        full_name = str(row.get("full_name") or "").strip()
        if not full_name:
            continue
        desc = str(row.get("description") or "").strip()[:300]
        topics = " ".join("[" + str(t) + "]" for t in (row.get("topics") or [])[:6])
        items.append(
            HotItem(
                source_id=source_id,
                title=full_name,
                heat=int(row.get("stargazers_count") or 0),
                url=str(row.get("html_url") or ("https://github.com/" + full_name)),
                extra=(" ".join(x for x in (desc, topics) if x)),
                repo=full_name,
            )
        )
    return items


def score_verticals(items: list[HotItem], verticals_cfg: dict[str, Any]) -> dict[str, dict[str, Any]]:
    scores: dict[str, dict[str, Any]] = {
        vid: {"vertical": vid, "score": 0.0, "hits": 0, "keyword_hits": {}, "top_items": []}
        for vid in verticals_cfg
    }
    for item in items:
        hay = item_haystack(item)
        for vid, vcfg in verticals_cfg.items():
            for kw in (str(k).lower() for k in vcfg.get("keywords", [])):
                if kw and kw in hay:
                    scores[vid]["score"] += item.weight * (
                        1.0 + min(max(item.heat, 0), 100000) / 100000.0
                    )
                    scores[vid]["hits"] += 1
                    hits = scores[vid]["keyword_hits"]
                    hits[kw] = hits.get(kw, 0) + 1
                    if len(scores[vid]["top_items"]) < 8:
                        scores[vid]["top_items"].append(item.to_dict())
                    break  # 每个条目对每个垂直只计一次
    for entry in scores.values():
        entry["keyword_hits"] = dict(sorted(entry["keyword_hits"].items(), key=lambda kv: -kv[1]))
        entry["top_items"] = sorted(entry["top_items"], key=lambda x: -int(x.get("heat") or 0))
    return dict(sorted(scores.items(), key=lambda kv: -kv[1]["score"]))


def repo_candidates(items: list[HotItem], block_terms: list[str]) -> list[dict[str, Any]]:
    """github trending 里的仓库候选; 描述命中黑名单的先在发现阶段剔除."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not item.repo or item.repo in seen:
            continue
        hay = item_haystack(item)
        if any(term_hit(hay, str(b).lower()) for b in block_terms):
            continue
        seen.add(item.repo)
        out.append(
            {
                "repo": item.repo,
                "stars_today": item.heat,
                "description": item.extra,
                "source": item.source_id,
                "url": item.url,
            }
        )
    return out


def _match_verticals(hay: str, verticals_cfg: dict[str, Any]) -> list[str]:
    return [
        vid
        for vid, vcfg in verticals_cfg.items()
        if any(str(k).lower() in hay for k in vcfg.get("keywords", []) if k)
    ]


# ---------------------------------------------------------------------------
# 建议与落盘: 只动 search_tags / long_tail / trend_repos
# ---------------------------------------------------------------------------

def propose_updates(
    scores: dict[str, dict[str, Any]],
    candidates_by_vertical: dict[str, list[dict[str, Any]]],
    topics: dict[str, Any],
    trends_cfg: dict[str, Any],
    compliance_cfg: dict[str, Any] | None = None,
) -> dict[str, Any]:
    block_terms = [str(b).lower() for b in ((compliance_cfg or {}).get("block_terms") or [])]

    def dirty(word: str) -> bool:
        low = word.lower()
        return bool(check_text(word)) or any(term_hit(low, b) for b in block_terms if b)

    apply_cfg = dict(trends_cfg.get("apply") or {})
    max_tags = int(apply_cfg.get("max_search_tags") or 6)
    max_tail = int(apply_cfg.get("max_long_tail") or 4)
    min_hits = int(apply_cfg.get("min_keyword_hits") or 2)
    by_id = {str(t.get("id")): t for t in topics.get("topics", [])}
    proposals: dict[str, Any] = {"updates": [], "skipped": []}
    for vid, score in scores.items():
        vcfg = trends_cfg.get("verticals", {}).get(vid) or {}
        topic = by_id.get(str(vcfg.get("topic_id") or ""))
        if topic is None:
            continue  # 未绑定专题的垂直 (如 hot-projects) 只进报告
        if int(score["hits"]) < min_hits:
            proposals["skipped"].append(
                {"vertical": vid, "topic_id": str(topic.get("id")), "reason": "今日热度不足"}
            )
            continue

        # long_tail: 今日热词优先, 保留 2 个原词位避免长尾池被一次冲掉
        fresh: list[str] = []
        for kw in score["keyword_hits"]:
            if len(kw) < 2 or kw.isdigit() or dirty(kw):
                continue
            if kw not in fresh and kw not in [str(x).lower() for x in topic.get("long_tail", [])]:
                fresh.append(kw)
            if len(fresh) >= max(1, max_tail - 2):
                break
        kept_old = [str(x) for x in topic.get("long_tail", []) if str(x).lower() not in fresh and not dirty(str(x))]
        new_tail = fresh + kept_old[: max_tail - len(fresh)] if max_tail > len(fresh) else fresh[:max_tail]
        new_tail = new_tail[:max_tail]

        # search_tags: 命中今日热词的 tag_pool 标签前置, 其余原序保留, 总数封顶
        pool = [str(t) for t in vcfg.get("tag_pool") or []]
        boosted = [
            t for t in pool
            if t.lower() not in [str(x).lower() for x in topic.get("search_tags", [])]
            and int(score["keyword_hits"].get(t.lower(), 0)) > 0
        ][:2]
        if boosted:
            old_tags = [str(x) for x in topic.get("search_tags", [])]
            new_tags = boosted + [t for t in old_tags if t.lower() not in {b.lower() for b in boosted}]
            new_tags = list(dict.fromkeys(new_tags))[:max_tags]
        else:
            new_tags = [str(x) for x in topic.get("search_tags", [])]

        fields: dict[str, Any] = {
            "long_tail": new_tail,
            "trend_repos": candidates_by_vertical.get(vid, [])[:8],
        }
        if boosted:
            fields["search_tags"] = new_tags
        proposals["updates"].append(
            {
                "vertical": vid,
                "topic_id": str(topic.get("id")),
                "fields": fields,
                "hot_summary": [x["title"] for x in score["top_items"][:5]],
            }
        )
    return proposals


def apply_proposals(topics_path: Path, proposals: dict[str, Any]) -> dict[str, Any]:
    """更新前先备份原文件 (*.bak 入 .gitignore), 原子写回."""
    path = Path(topics_path)
    raw = path.read_bytes()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(path.stem + "_" + stamp + ".bak")
    backup.write_bytes(raw)
    topics = json.loads(raw.decode("utf-8"))
    by_id = {str(t.get("id")): t for t in topics.get("topics", [])}
    changed: list[str] = []
    for upd in proposals.get("updates", []):
        topic = by_id.get(str(upd.get("topic_id")))
        if topic is None:
            continue
        topic.update(dict(upd.get("fields") or {}))
        changed.append(str(upd.get("topic_id")))
    write_json_atomic(path, topics)
    return {"path": str(path), "backup": str(backup), "changed": changed}


# ---------------------------------------------------------------------------
# 编排: 抓全部源 -> 评分 -> 建议 -> (可选) 应用 -> 报告
# ---------------------------------------------------------------------------

def run_trends(
    trends_cfg: dict[str, Any],
    compliance_cfg: dict[str, Any],
    topics_path: Path,
    out_root: Path,
    fixture: Path | None = None,
    apply: bool = False,
) -> dict[str, Any]:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ua = str(trends_cfg.get("user_agent") or "github-bundle-engine/1.0")
    timeout = float(trends_cfg.get("fetch_timeout_seconds") or 20)
    retries = int(trends_cfg.get("fetch_retries") or 3)
    interval = float(trends_cfg.get("min_interval_seconds") or 1.5)
    verticals_cfg = dict(trends_cfg.get("verticals") or {})
    fixture_data: dict[str, Any] | None = None
    if fixture is not None:
        fixture_data = dict(json.loads(Path(fixture).read_text(encoding="utf-8")).get("sources") or {})

    raw_dir = Path(out_root) / "cache" / "trends"
    raw_dir.mkdir(parents=True, exist_ok=True)
    items: list[HotItem] = []
    source_results: list[dict[str, Any]] = []
    warnings: list[str] = []

    for src in trends_cfg.get("sources", []):
        sid = str(src.get("id") or "source")
        stype = str(src.get("type") or "")
        try:
            if fixture_data is not None:
                if sid not in fixture_data:
                    raise TrendsError("夹具缺源 " + sid)
                payload = fixture_data[sid]
            else:
                extra = dict(src.get("headers") or {})
                if stype == "github_search":
                    token = os.environ.get("GITHUB_TOKEN", "")
                    if token:
                        extra["Authorization"] = "Bearer " + token
                raw = fetch_bytes(
                    str(src.get("url") or ""),
                    user_agent=ua, timeout=timeout, retries=retries, min_interval=interval,
                    extra_headers=extra,
                )
                (raw_dir / (sid + ".raw")).write_bytes(raw)
                payload = raw
            if stype == "github_trending":
                text = payload.decode("utf-8", "replace") if isinstance(payload, (bytes, bytearray)) else str(payload)
                parsed = parse_github_trending(text, sid)
            elif stype == "json_api":
                data = json.loads(payload.decode("utf-8")) if isinstance(payload, (bytes, bytearray)) else payload
                parsed = parse_json_api(data, src, sid)
            elif stype == "github_search":
                data = json.loads(payload.decode("utf-8")) if isinstance(payload, (bytes, bytearray)) else payload
                parsed = parse_github_search(data, sid)
            else:
                raise TrendsError("未知源类型 " + stype)
            weight = float(src.get("weight") or 1.0)
            for it in parsed:
                it.weight = weight
            items.extend(parsed)
            source_results.append({"id": sid, "type": stype, "items": len(parsed), "ok": True})
        except (TrendsError, ValueError, KeyError, OSError) as exc:
            warnings.append(sid + ": " + str(exc))
            source_results.append({"id": sid, "type": stype, "items": 0, "ok": False, "error": str(exc)})

    scores = score_verticals(items, verticals_cfg)
    candidates = repo_candidates(items, list(compliance_cfg.get("block_terms") or []))
    candidates_by_vertical: dict[str, list[dict[str, Any]]] = {vid: [] for vid in verticals_cfg}
    for cand in candidates:
        hay = (cand["repo"] + " " + cand["description"]).lower()
        for vid in _match_verticals(hay, verticals_cfg):
            candidates_by_vertical[vid].append(cand)
    for vid in candidates_by_vertical:
        candidates_by_vertical[vid] = candidates_by_vertical[vid][:8]

    topics = json.loads(Path(topics_path).read_text(encoding="utf-8"))
    proposals = propose_updates(scores, candidates_by_vertical, topics, trends_cfg, compliance_cfg)
    applied: dict[str, Any] | None = None
    if apply and proposals["updates"]:
        applied = apply_proposals(Path(topics_path), proposals)

    report = {
        "schema": REPORT_SCHEMA,
        "generated_at": generated,
        "fixture": bool(fixture_data is not None),
        "items_total": len(items),
        "sources": source_results,
        "scores": scores,
        "candidates": candidates_by_vertical,
        "proposals": proposals,
        "applied": applied,
        "warnings": warnings,
    }
    reports_dir = Path(out_root) / "reports"
    write_json_atomic(reports_dir / ("trends_" + generated[:10] + ".json"), report)
    write_json_atomic(raw_dir / "latest.json", report)
    _write_markdown(reports_dir / ("trends_" + generated[:10] + ".md"), report)
    return report


def _write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# 热点发现日报 " + str(report.get("generated_at", ""))[:10],
        "",
        "- 抓取条目: " + str(report.get("items_total", 0)),
        "- 告警: " + ("; ".join(report.get("warnings") or []) or "无"),
        "",
    ]
    for vid, score in (report.get("scores") or {}).items():
        lines.append("## " + str(vid))
        lines.append("")
        lines.append("得分 " + str(round(float(score.get("score") or 0), 2))
                     + " / 命中 " + str(score.get("hits", 0)))
        kws = score.get("keyword_hits") or {}
        if kws:
            lines.append("")
            lines.append("热词: " + ", ".join(list(kws)[:8]))
        items = score.get("top_items") or []
        if items:
            lines.append("")
            for it in items[:5]:
                lines.append("- [" + str(it.get("source")) + "] " + str(it.get("title"))
                             + " (热度 " + str(it.get("heat")) + ")")
        lines.append("")
    for upd in (report.get("proposals") or {}).get("updates") or []:
        lines.append("## 建议刷新: " + str(upd.get("topic_id")) + " (" + str(upd.get("vertical")) + ")")
        lines.append("")
        lines.append("- 热点: " + "; ".join(str(x) for x in upd.get("hot_summary") or []))
        fields = upd.get("fields") or {}
        if "search_tags" in fields:
            lines.append("- search_tags -> " + ", ".join(str(x) for x in fields["search_tags"]))
        lines.append("- long_tail -> " + ", ".join(str(x) for x in fields.get("long_tail") or []))
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
