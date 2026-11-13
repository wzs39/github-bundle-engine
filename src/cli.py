"""命令行编排: build / bind-pan / schedule / verify / report / selftest / trends / daily.

用法:
  python -m src.cli selftest --out OUTPUT_DIR
  python -m src.cli selftest --all-topics --out OUTPUT_DIR
  python -m src.cli trends --out OUTPUT_DIR                       # 读热门总结站, 出发现报告
  python -m src.cli trends --apply --out OUTPUT_DIR               # 建议写回 topics.json (先备份)
  python -m src.cli daily --out OUTPUT_DIR                        # 热点->刷新专题->构建->校验->排程
  python -m src.cli build --topic py-office --out OUTPUT_DIR
  python -m src.cli build --all --out OUTPUT_DIR
  python -m src.cli bind-pan --topic py-office --share-url URL --extract-code CODE --out OUTPUT_DIR
  python -m src.cli schedule --days 7 --out OUTPUT_DIR
  python -m src.cli verify --out OUTPUT_DIR
  python -m src.cli report --out OUTPUT_DIR --orders 7 --pan-new 3

网络动作集中在 build 与 trends; 其余子命令全程离线.
daily 里 trends 建议会写回 config/topics.json (带 *.bak 备份),
价格 / 受众 / 场景导语等文案字段永不自动修改.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
import tarfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from .compliance import (
    check_declaration,
    check_text,
    has_license,
    load_config,
    read_declaration,
    screen_repo,
    select_release_assets,
)
from .downloader import write_json_atomic
from .gh_client import GitHubClient, Repo
from .listing import (
    render_auto_reply,
    render_daily_report,
    render_detail,
    render_listing_plan,
    render_title,
    save_listing_bundle,
)
from .packer import build_topic, safe_name
from .pan import bind as bind_pan
from .pan import find_manifests
from .scheduler import build_schedule, render_schedule_md
from .trends import run_trends

ENGINE_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TOPICS = ENGINE_ROOT / "config" / "topics.json"
DEFAULT_SETTINGS = ENGINE_ROOT / "config" / "settings.json"
DEFAULT_COMPLIANCE = ENGINE_ROOT / "config" / "compliance.json"
DEFAULT_TRENDS = ENGINE_ROOT / "config" / "trends.json"


def log(msg: str) -> None:
    print("[github-bundle] " + msg, flush=True)


def load_all(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    topics = load_config(args.topics)
    settings = load_config(args.settings)
    compliance = load_config(args.compliance)
    compliance["size_min_mb"] = topics.get("size_min_mb", 500)
    compliance["size_max_mb"] = topics.get("size_max_mb", 2048)
    return topics, settings, compliance


def build_query(topic: dict[str, Any]) -> str:
    tags = [str(t) for t in topic.get("search_tags", [])]
    parts = ["(" + " OR ".join(tags) + ")"] if tags else []
    extra = str(topic.get("extra_query") or "").strip()
    if extra:
        parts.append(extra)
    return " ".join(parts) if parts else "stars:>1000"


def _fixture_repo(idx: int) -> Repo:
    return Repo(
        full_name="fixture-org/demo-project-" + str(idx),
        html_url="https://github.com/fixture-org/demo-project-" + str(idx),
        description="离线夹具项目 " + str(idx) + " 用于验证全链路, 含中文简介与部署说明",
        stars=4200 - idx * 137,
        pushed_at="2026-08-1" + str(idx % 9) + "T08:30:00Z",
        default_branch="main",
        license_key="MIT" if idx % 2 else "Apache-2.0",
        license_name="MIT License" if idx % 2 else "Apache License 2.0",
        topics=["automation", "python"],
    )


def make_fixture_archive(cache: Path, repo: Repo) -> tuple[Path, dict[str, Any]]:
    """构造合法 tar.gz: 含 LICENSE / README / 源码, 供 selftest 离线跑通."""
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / (safe_name(repo.full_name) + ".tar.gz")
    root = repo.full_name.split("/")[-1] + "-main"
    with tarfile.open(path, "w:gz") as tf:
        files = {
            root + "/LICENSE": b"MIT License\nCopyright (c) 2026 fixture-org\n",
            root + "/README.md": b"# " + repo.full_name.encode("utf-8") + b"\n\nDemo source.\n",
            root + "/src/main.py": b"def main():\n    print('hello')\n",
            root + "/requirements.txt": b"requests>=2.28\n",
        }
        for name, payload in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mtime = int(time.time())
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(payload))
    import hashlib

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return path, {"url": "fixture://" + path.name, "sha256": digest, "bytes": path.stat().st_size}


def cmd_selftest(args: argparse.Namespace) -> int:
    """离线夹具跑通全链路. 默认 1 个专题, --all-topics 覆盖全部 4 个."""
    topics, _settings, compliance = load_all(args)
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    declaration = read_declaration(ENGINE_ROOT, compliance)
    issues = check_declaration(declaration)
    if issues:
        log("FAIL 合规声明: " + "; ".join(issues))
        return 1

    selected = topics["topics"] if args.all_topics else topics["topics"][:1]
    (root / "cache").mkdir(parents=True, exist_ok=True)
    exe = root / "cache" / "fixture-setup.exe"
    exe.write_bytes(b"MZ\x90\x00 fixture installer placeholder\n")

    all_checks: dict[str, bool] = {"declaration_ok": True}
    built: list[dict[str, Any]] = []
    for tno, topic in enumerate(selected, start=1):
        tag = str(topic["id"])
        repos = [_fixture_repo(i) for i in range(1, 4)]
        for r in repos:
            r.full_name = "fixture-" + tag + "/" + r.full_name.split("/")[-1]
            r.html_url = "https://github.com/" + r.full_name
        archives: list[tuple[Repo, Path, dict[str, Any]]] = []
        for repo in repos:
            ok, reason = screen_repo(repo, compliance)
            if not ok:
                log("FAIL 合规闸误判: " + reason)
                return 1
            tar_path, meta = make_fixture_archive(root / "cache", repo)
            archives.append((repo, tar_path, meta))
        release_files = {repos[0].full_name: [(str(exe), "fixture-setup.exe")]}

        result = build_topic(
            topic=topic,
            repos=repos,
            archives=archives,
            release_files=release_files,
            root=root,
            engine_root=ENGINE_ROOT,
            cfg=compliance,
            excluded=[],
        )
        listing = save_listing_bundle(
            root, topic, result["manifest"], declaration,
            share_url="[PAN_SHARE_URL]", extract_code="[PAN_EXTRACT_CODE]",
        )
        manifest_text = (Path(result["folder"]) / "00_项目清单与中文简介说明.md").read_text(encoding="utf-8")
        checks = {
            tag + ":repo_count": result["manifest"]["repo_count"] == 3,
            tag + ":license_present": all(r["license_in_archive"] for r in result["manifest"]["repos"]),
            tag + ":four_entries": _has_four_entries(Path(result["folder"])),
            tag + ":manifest_ok": (Path(result["folder"]) / "_manifest.json").is_file(),
            tag + ":intro_in_manifest": bool(result["manifest"]["topic"]["intro"]),
            tag + ":intro_in_doc": "## 这套合集解决什么" in manifest_text,
            tag + ":listing_clean": listing["clean"],
            tag + ":detail_clean": not check_text(render_detail(topic, result["manifest"], declaration)),
            tag + ":reply_clean": not check_text(render_auto_reply(topic, "[PAN_SHARE_URL]", "[PAN_EXTRACT_CODE]")),
            tag + ":title_ok": len(render_title(topic)) <= 60,
            tag + ":plan_ok": render_listing_plan(topic, result["manifest"])["stock_min"] == 50,
        }
        all_checks.update(checks)
        built.append({"topic": tag, "folder": result["folder"], "mb": result["manifest"]["package_mb"]})
        log("  专题 " + str(tno) + "/" + str(len(selected)) + " 完成: " + result["folder"])

    report = render_daily_report(
        date=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        link_count=6,
        exposures=412,
        wants=23,
        orders=3,
        front_revenue=3 * float(selected[0]["price"]),
        pan_new_users=2,
        pan_saves=9,
        pan_commission=2 * 8.5 + 9 * 0.4,
    )
    write_json_atomic(root / "reports" / "selftest_daily.json", report)
    write_json_atomic(root / "reports" / "selftest_builds.json", {"built": built})

    for key, value in all_checks.items():
        log(("PASS " if value else "FAIL ") + key)
    failed = [k for k, v in all_checks.items() if not v]
    if failed:
        log("SELFTEST FAILED: " + ", ".join(failed))
        return 1
    log("SELFTEST PASS · " + str(len(built)) + " 个专题包")
    log("上架物料: " + str(root / "listings"))
    log("复盘样例: " + str(root / "reports" / "selftest_daily.json"))
    return 0


def _has_four_entries(folder: Path) -> bool:
    names = {p.name for p in folder.iterdir()}
    required = {
        "00_项目清单与中文简介说明.md",
        "01_新手环境配置与国内镜像加速.txt",
        "02_Windows免安装可执行程序包",
        "03_精选开源项目源码合集",
    }
    return required.issubset(names)


def cmd_build(args: argparse.Namespace) -> int:
    topics, settings, compliance = load_all(args)
    root = Path(args.out)
    root.mkdir(parents=True, exist_ok=True)
    wanted = {t["id"] for t in topics["topics"]} if args.all else {args.topic}
    selected = [t for t in topics["topics"] if t["id"] in wanted]
    if not selected:
        log("FAIL 未找到专题: " + ", ".join(sorted(wanted)))
        return 1

    declaration = read_declaration(ENGINE_ROOT, compliance)
    issues = check_declaration(declaration)
    if issues:
        log("FAIL 合规声明: " + "; ".join(issues))
        return 1

    client = GitHubClient(
        token="",
        api_root=str(settings.get("api_root", "https://api.github.com")),
        timeout=float(settings.get("timeout_seconds", 30)),
        max_retries=int(settings.get("max_retries", 4)),
        min_interval=float(settings.get("min_interval_seconds", 2.0)),
        mirrors=list(settings.get("download_mirrors", [])),
    )
    cache = root / "cache"
    summary: list[dict[str, Any]] = []
    for topic in selected:
        log("构建专题: " + str(topic["name"]))
        query = build_query(topic)
        found = client.search(
            query,
            min_stars=int(topic["min_stars"]),
            pushed_after_days=int(topic["pushed_after_days"]),
            limit=int(topic["repo_limit"]) + 12,
        )
        kept: list[Repo] = []
        excluded: list[dict[str, str]] = []
        for repo in found:
            ok, reason = screen_repo(repo, compliance)
            if ok:
                kept.append(repo)
            else:
                excluded.append({"repo": repo.full_name, "reason": reason})
                log("  排除 " + repo.full_name + " -> " + reason)
            if len(kept) >= int(topic["repo_limit"]):
                break
        archives: list[tuple[Repo, Path, dict[str, Any]]] = []
        release_files: dict[str, list[tuple[str, str]]] = {}
        for idx, repo in enumerate(kept, start=1):
            tar_path = cache / (safe_name(repo.full_name) + ".tar.gz")
            log("  [" + str(idx) + "/" + str(len(kept)) + "] 下载源码 " + repo.full_name)
            meta = client.download(client.source_url(repo), tar_path)
            ok, why = has_license(tar_path, compliance)
            if not ok:
                excluded.append({"repo": repo.full_name, "reason": why})
                log("  排除(归档校验) " + repo.full_name + " -> " + why)
                continue
            archives.append((repo, tar_path, meta))
            assets = select_release_assets(
                client.latest_release_assets(repo.full_name), compliance
            )
            for asset in assets[:2]:
                dest = cache / ("asset_" + safe_name(repo.full_name) + "_" + safe_name(asset["name"]))
                log("  下载 Release " + asset["name"])
                client.download(asset["url"], dest)
                release_files.setdefault(repo.full_name, []).append((str(dest), asset["name"]))
        if not archives:
            log("  本专题零收录, 跳过打包: " + str(topic["id"]))
            summary.append({"topic": topic["id"], "status": "empty"})
            continue
        result = build_topic(
            topic=topic,
            repos=[a[0] for a in archives],
            archives=archives,
            release_files=release_files,
            root=root,
            engine_root=ENGINE_ROOT,
            cfg=compliance,
            excluded=excluded,
        )
        share = str(args.pan_share_url or "")
        code = str(args.pan_extract_code or "")
        listing = save_listing_bundle(root, topic, result["manifest"], declaration, share, code)
        bound = False
        placeholder = share.startswith("[") or code.startswith("[")
        if share and code and not placeholder:
            bind_pan(root, str(topic["id"]), share, code)
            bound = True
        elif share or code:
            log("  提示: 传入的是占位链接, 保留文案占位但不写 manifest; 用 bind-pan 回填真实推广链")
        summary.append(
            {
                "topic": topic["id"],
                "status": "built",
                "folder": result["folder"],
                "repos": result["manifest"]["repo_count"],
                "mb": result["manifest"]["package_mb"],
                "size_ok": result["manifest"]["size_ok"],
                "excluded": len(excluded),
                "listing": listing,
                "pan_configured": bound,
            }
        )
        log("  完成 " + result["folder"] + " / " + str(result["manifest"]["package_mb"]) + " MB")
        if not result["manifest"]["size_ok"]:
            log("  警告: 包体积未落在 " + str(topics.get("size_min_mb", 500)) + "-"
                + str(topics.get("size_max_mb", 2048)) + " MB, 上架前补 Release 包或提高 repo_limit")
    write_json_atomic(
        root / "reports" / ("build_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json"),
        {"schema": "github-bundle-engine/build@1", "summary": summary},
    )
    return 0


def cmd_trends(args: argparse.Namespace) -> int:
    """读热门总结站 -> 垂直归属 -> (可选) 把刷新建议写回 topics.json."""
    compliance = load_config(args.compliance)
    trends_cfg = load_config(getattr(args, "trends_config") or DEFAULT_TRENDS)
    fixture_arg = str(getattr(args, "fixture", "") or "")
    fixture = Path(fixture_arg) if fixture_arg else None
    report = run_trends(
        trends_cfg=trends_cfg,
        compliance_cfg=compliance,
        topics_path=Path(args.topics),
        out_root=Path(args.out),
        fixture=fixture,
        apply=bool(getattr(args, "apply", False)),
    )
    ok_sources = sum(1 for s in report["sources"] if s.get("ok"))
    log("热点条目: " + str(report["items_total"]) + " / 源成功 "
        + str(ok_sources) + "/" + str(len(report["sources"])))
    for vid, score in report["scores"].items():
        if score["hits"]:
            log("  [" + vid + "] 得分 " + str(round(float(score["score"]), 2)) + " 热词: "
                + ", ".join(list(score["keyword_hits"])[:6]))
    for upd in report["proposals"]["updates"]:
        log("  建议刷新 " + str(upd["topic_id"]) + " (" + str(upd["vertical"]) + "): long_tail -> "
            + ", ".join(str(x) for x in (upd["fields"].get("long_tail") or [])))
    for skipped in report["proposals"]["skipped"]:
        log("  跳过 " + str(skipped["topic_id"]) + ": " + str(skipped["reason"]))
    for w in report["warnings"]:
        log("  WARN " + w)
    if report.get("applied"):
        log("已应用: " + str(report["applied"]["path"]) + " (备份 " + str(report["applied"]["backup"]) + ")")
    log("报告: " + str(Path(args.out) / "reports"))
    if report["items_total"] == 0:
        log("FAIL 所有热点源零数据: 断网或站点改版时发生, 原始响应留档在 OUTPUT_DIR/cache/trends/")
        return 1
    return 0


def cmd_daily(args: argparse.Namespace) -> int:
    """一条龙: 热点发现 -> 应用刷新 -> 构建 -> 校验 -> 排程.

    设计目标是无人在场也能跑: 单段失败降级为 WARN 不中断,
    热点零数据(断网/站点改版)时跳过构建但仍返回 1 让计划任务告警.
    """
    args.apply = not bool(getattr(args, "no_apply", False))
    log("[1/4] 热点发现")
    trends_rc = cmd_trends(args)
    if trends_rc != 0:
        log("热点阶段失败, 后续跳过 (daily 退出码 1)")
        return 1
    if args.skip_build:
        log("[2/4] 构建已按参数跳过")
        return 0
    log("[2/4] 构建专题包")
    build_ns = argparse.Namespace(
        topics=str(args.topics),
        settings=str(args.settings),
        compliance=str(args.compliance),
        out=str(args.out),
        topic="",
        all=True,
        pan_share_url=str(getattr(args, "pan_share_url", "") or ""),
        pan_extract_code=str(getattr(args, "pan_extract_code", "") or ""),
    )
    if cmd_build(build_ns) != 0:
        log("  构建失败, 校验与排程跳过 (daily 退出码 1)")
        return 1
    if not args.skip_verify:
        log("[3/4] 校验产物")
        verify_ns = argparse.Namespace(
            topics=str(args.topics), settings=str(args.settings),
            compliance=str(args.compliance), out=str(args.out),
        )
        if cmd_verify(verify_ns) != 0:
            log("  WARN 校验存在 FAIL 项, 人工检查后再上架")
    if not args.skip_schedule:
        log("[4/4] 上架排程")
        schedule_ns = argparse.Namespace(
            topics=str(args.topics), settings=str(args.settings),
            compliance=str(args.compliance), out=str(args.out),
            start="", days=int(getattr(args, "days", 7)), per_day=2, interval=60,
            existing_links=int(getattr(args, "existing_links", 0)),
        )
        if cmd_schedule(schedule_ns) != 0:
            log("  WARN 排程未生成 (首次运行无历史包时正常)")
    return 0


def cmd_bind_pan(args: argparse.Namespace) -> int:
    """把已报备渠道生成的推广链回填到 _manifest.json 与自动发货文案."""
    root = Path(args.out)
    topic_id = str(args.topic or "")
    share = str(args.share_url or "")
    code = str(args.extract_code or "")
    uid = str(args.promote_uid or "")
    result = bind_pan(
        root=root,
        topic_id=topic_id,
        share_url=share,
        extract_code=code,
        promote_uid=uid,
        channel_reported=not args.unreported,
    )
    log("已绑定 " + topic_id + " -> " + result["share_url"])
    log("manifest: " + result["manifest"])
    log("auto_reply: " + result["auto_reply"])
    log("渠道报备: " + ("是" if result["channel_reported"] else "否 (T+1 佣金需先完成报备)"))
    return 0


def cmd_schedule(args: argparse.Namespace) -> int:
    """按 Day 6-7 / 稳定期节奏产出上架排程 JSON 与 Markdown."""
    topics, _settings, _compliance = load_all(args)
    root = Path(args.out)
    manifests: dict[str, dict[str, Any]] = {}
    for tid, path in find_manifests(root).items():
        manifests[tid] = json.loads(path.read_text(encoding="utf-8"))
    if not manifests:
        log("FAIL 未找到专题包, 先跑 selftest --all-topics 或 build")
        return 1
    selected = [t for t in topics["topics"] if t["id"] in manifests]
    start = (
        datetime.fromisoformat(args.start)
        if args.start
        else datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
    )
    schedule = build_schedule(
        topics=selected,
        manifests=manifests,
        start=start,
        days=int(args.days),
        per_day=int(args.per_day),
        interval_minutes=int(args.interval),
        existing_links=int(args.existing_links),
    )
    dest = root / "reports"
    dest.mkdir(parents=True, exist_ok=True)
    json_path = dest / ("schedule_" + start.date().isoformat() + ".json")
    md_path = dest / ("schedule_" + start.date().isoformat() + ".md")
    write_json_atomic(json_path, schedule)
    md_path.write_text(render_schedule_md(schedule), encoding="utf-8", newline="\n")
    log("排程 " + str(schedule["window"]["slots"]) + " 个槽 / 间隔 "
        + str(schedule["window"]["interval_minutes"]) + " 分钟 / 链接 "
        + str(schedule["shelf"]["existing_links"]) + " -> "
        + str(schedule["shelf"]["final_links"]))
    log("JSON: " + str(json_path))
    log("Markdown: " + str(md_path))
    unbound = [s["topic_id"] for s in schedule["slots"] if "待补" in s["notes"]]
    if unbound:
        log("待 bind-pan: " + ", ".join(sorted(set(unbound))))
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    _topics, _settings, compliance = load_all(args)
    root = Path(args.out)
    declaration = read_declaration(ENGINE_ROOT, compliance)
    problems: list[str] = []
    manifests = sorted(root.glob("2026持续更新_*合集/_manifest.json"))
    if not manifests:
        log("FAIL 未找到已生成包, 先跑 selftest 或 build")
        return 1
    for mf in manifests:
        data = json.loads(mf.read_text(encoding="utf-8"))
        folder = mf.parent
        if not _has_four_entries(folder):
            problems.append(folder.name + ": 四级目录不全")
        for row in data.get("repos", []):
            if not row.get("license_in_archive"):
                problems.append(folder.name + "/" + row["full_name"] + ": LICENSE 缺失")
            src = folder / "03_精选开源项目源码合集" / row["folder"]
            if not src.is_dir():
                problems.append(folder.name + ": 源码目录缺失 " + row["folder"])
        for rel in ("00_项目清单与中文简介说明.md", "01_新手环境配置与国内镜像加速.txt"):
            text = (folder / rel).read_text(encoding="utf-8")
            problems.extend(folder.name + "/" + rel + ": " + x for x in check_text(text))
        if declaration and declaration not in (folder / "00_项目清单与中文简介说明.md").read_text(encoding="utf-8"):
            problems.append(folder.name + ": 清单内缺少合规声明")
    for entry in sorted(root.glob("listings/*/xianyu_detail.md")):
        problems.extend(entry.name + ": " + x for x in check_text(entry.read_text(encoding="utf-8")))
    for entry in sorted(root.glob("listings/*/auto_reply.txt")):
        problems.extend(entry.name + ": " + x for x in check_text(entry.read_text(encoding="utf-8")))
    if problems:
        for p in problems:
            log("FAIL " + p)
        return 1
    bound = 0
    size_bad: list[str] = []
    for mf in manifests:
        data = json.loads(mf.read_text(encoding="utf-8"))
        if (data.get("pan") or {}).get("share_url"):
            bound += 1
        if not data.get("size_ok"):
            size_bad.append(str(data.get("folder", mf.parent.name)) + " ("
                            + str(data.get("package_mb", 0)) + " MB)")
    log("VERIFY PASS · " + str(len(manifests)) + " 个专题包 / 4 级目录 / LICENSE / 文案红线 全过")
    log("推广链绑定: " + str(bound) + "/" + str(len(manifests)) + " (未绑定用 bind-pan 回填)")
    if size_bad:
        log("体积未达 500-2048 MB: " + str(len(size_bad)) + " 个 -> " + "; ".join(size_bad))
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    root = Path(args.out)
    report = render_daily_report(
        date=str(args.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        link_count=int(args.links),
        exposures=int(args.exposures),
        wants=int(args.wants),
        orders=int(args.orders),
        front_revenue=float(args.front_revenue),
        pan_new_users=int(args.pan_new),
        pan_saves=int(args.pan_saves),
        pan_commission=float(args.pan_commission),
    )
    dest = root / "reports" / ("daily_" + report["date"] + ".json")
    write_json_atomic(dest, report)
    log(json.dumps(report, ensure_ascii=False, indent=2))
    log("已写入 " + str(dest))
    return 0


def build_parser() -> argparse.ArgumentParser:
    # 全局参数同时接受 "cli --out X selftest" 与 "cli selftest --out X" 两种写法.
    # 子命令副本用 SUPPRESS, 未显式给出时保留顶层默认值, 不被子解析器默认值覆盖.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--topics", default=argparse.SUPPRESS)
    common.add_argument("--settings", default=argparse.SUPPRESS)
    common.add_argument("--compliance", default=argparse.SUPPRESS)
    common.add_argument("--out", default=argparse.SUPPRESS)

    p = argparse.ArgumentParser(prog="github-bundle-engine", description="GitHub 精选专题合集自动化生产引擎")
    p.add_argument("--topics", default=str(DEFAULT_TOPICS))
    p.add_argument("--settings", default=str(DEFAULT_SETTINGS))
    p.add_argument("--compliance", default=str(DEFAULT_COMPLIANCE))
    p.add_argument("--out", default="OUTPUT_DIR")
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", parents=[common], help="抓取并生成专题包")
    b.add_argument("--topic", default="")
    b.add_argument("--all", action="store_true")
    b.add_argument("--pan-share-url", default="")
    b.add_argument("--pan-extract-code", default="")
    b.set_defaults(func=cmd_build)

    t = sub.add_parser("trends", parents=[common], help="读热门总结站, 出专题刷新建议")
    t.add_argument("--trends-config", default=str(DEFAULT_TRENDS))
    t.add_argument("--apply", action="store_true", help="把建议写回 topics.json (先自动备份)")
    t.add_argument("--fixture", default="", help="离线夹具 JSON, sources 字段按源 id 给原始响应")
    t.set_defaults(func=cmd_trends)

    d = sub.add_parser("daily", parents=[common], help="一条龙: 热点 -> 刷新专题 -> 构建 -> 校验 -> 排程")
    d.add_argument("--trends-config", default=str(DEFAULT_TRENDS))
    d.add_argument("--no-apply", action="store_true", help="只出发现报告, 不写回 topics.json")
    d.add_argument("--skip-build", action="store_true")
    d.add_argument("--skip-verify", action="store_true")
    d.add_argument("--skip-schedule", action="store_true")
    d.add_argument("--fixture", default="", help="离线夹具 JSON, 测试与无网试跑用")
    d.add_argument("--days", type=int, default=7)
    d.add_argument("--existing-links", type=int, default=0)
    d.add_argument("--pan-share-url", default="")
    d.add_argument("--pan-extract-code", default="")
    d.set_defaults(func=cmd_daily)

    bp = sub.add_parser("bind-pan", parents=[common], help="回填已报备的网盘推广链与提取码")
    bp.add_argument("--topic", required=True)
    bp.add_argument("--share-url", required=True)
    bp.add_argument("--extract-code", required=True)
    bp.add_argument("--promote-uid", default="")
    bp.add_argument("--unreported", action="store_true", help="渠道尚未报备 (T+1 佣金不成立)")
    bp.set_defaults(func=cmd_bind_pan)

    sc = sub.add_parser("schedule", parents=[common], help="生成闲鱼上架排程")
    sc.add_argument("--start", default="", help="ISO 起始时间, 默认当天 09:00")
    sc.add_argument("--days", type=int, default=7)
    sc.add_argument("--per-day", type=int, default=2)
    sc.add_argument("--interval", type=int, default=60)
    sc.add_argument("--existing-links", type=int, default=0)
    sc.set_defaults(func=cmd_schedule)

    v = sub.add_parser("verify", parents=[common], help="校验已生成包")
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("selftest", parents=[common], help="离线夹具跑通全链路")
    s.add_argument("--all-topics", action="store_true", help="覆盖全部 4 个专题")
    s.set_defaults(func=cmd_selftest)

    r = sub.add_parser("report", parents=[common], help="生成每日 90 分钟 SOP 复盘 JSON")
    r.add_argument("--date", default="")
    r.add_argument("--links", type=int, default=20)
    r.add_argument("--exposures", type=int, default=2000)
    r.add_argument("--wants", type=int, default=90)
    r.add_argument("--orders", type=int, default=7)
    r.add_argument("--front-revenue", type=float, default=32.5)
    r.add_argument("--pan-new", type=int, default=3)
    r.add_argument("--pan-saves", type=int, default=24)
    r.add_argument("--pan-commission", type=float, default=33.6)
    r.set_defaults(func=cmd_report)
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        log("中断")
        return 130
    except (ValueError, OSError, RuntimeError) as exc:
        log("ERROR " + repr(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
