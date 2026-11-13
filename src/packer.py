"""标准化交付目录生成 (策略书 3).

产出:
  OUTPUT_DIR/2026持续更新_GitHub精选【专题名称】合集/
    00_项目清单与中文简介说明.md
    01_新手环境配置与国内镜像加速.txt
    02_Windows免安装可执行程序包/
    03_精选开源项目源码合集/01_owner_repo/...
    _manifest.json                      # 机读清单 含 sha256 与协议
不压成单个死压缩包: 多级目录直接可预览, 方便网盘一键转存.
"""
from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .compliance import check_declaration, read_declaration
from .downloader import dir_size, extract_source, place_release_asset, write_json_atomic
from .gh_client import Repo

YEAR = "2026"
_SLUG = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._-]+")


def safe_name(text: str) -> str:
    cleaned = _SLUG.sub("_", text).strip("_")
    return cleaned[:80] or "unnamed"


def package_dir(root: str | Path, topic_name: str) -> Path:
    folder = YEAR + "持续更新_GitHub精选【" + safe_name(topic_name) + "】合集"
    return Path(root) / folder


def _render(template: str, mapping: dict[str, str]) -> str:
    out = template
    for key, value in mapping.items():
        out = out.replace("{{" + key + "}}", value)
    return out


def render_project_manifest(
    topic: dict[str, Any],
    rows: list[dict[str, Any]],
    declaration: str,
    intro: list[str] | None = None,
) -> str:
    lines: list[str] = []
    lines.append("# " + str(topic["name"]) + " · 项目清单与中文简介说明")
    lines.append("")
    lines.append("> 生成时间 (UTC): " + datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"))
    lines.append("> 收录项目: " + str(len(rows)) + " 个 | 定价: " + str(topic["price"]) + " 元 (" + str(topic["price_tier"]) + ")")
    lines.append("> 目标客群: " + str(topic["audience"]))
    lines.append("")
    lines.append("## 这套合集解决什么")
    lines.append("")
    for para in intro or []:
        lines.append(str(para))
        lines.append("")
    if not intro:
        lines.append("按业务场景归类的 GitHub 高星开源项目合集, 附中文部署清单与国内镜像配置.")
        lines.append("")
    lines.append("## 合规声明")
    lines.append("")
    lines.append(declaration)
    lines.append("")
    lines.append("## 收录列表")
    lines.append("")
    lines.append("| 编号 | 项目 | Star | 最近更新 | 开源协议 | 功能摘要 | 原仓库 |")
    lines.append("| --- | --- | ---: | --- | --- | --- | --- |")
    for row in rows:
        lines.append(
            "| " + str(row["index"])
            + " | " + str(row["full_name"])
            + " | " + str(row["stars"])
            + " | " + str(row["pushed_at"])[:10]
            + " | " + str(row["license_key"])
            + " | " + str(row["description"]).replace("|", "/")[:80]
            + " | " + str(row["html_url"]) + " |"
        )
    lines.append("")
    lines.append("## 每个项目的落地说明")
    lines.append("")
    for row in rows:
        lines.append("### " + str(row["index"]) + ". " + str(row["full_name"]))
        lines.append("")
        lines.append("- 原仓库: " + str(row["html_url"]))
        lines.append("- 开源协议: " + str(row["license_key"]) + " (" + str(row["license_name"]) + ")")
        lines.append("- 源码目录: `03_精选开源项目源码合集/" + str(row["folder"]) + "/`")
        lines.append("- 源码归档 SHA-256: `" + str(row["archive_sha256"]) + "`")
        lines.append("- 归档内 LICENSE: " + str(row["license_in_archive"]))
        lines.append("- Release 安装包: " + (", ".join(row["release_assets"]) or "无 (见 02 目录说明)"))
        lines.append("- 中文说明: " + str(row["description"] or "见原仓库 README"))
        lines.append("")
    lines.append("## 免责与使用")
    lines.append("")
    lines.append("各项目版权归原作者所有, 使用与再分发以各自 LICENSE 为准.")
    lines.append("本合集仅提供分类整理, 中文摘要与网盘目录整理服务.")
    lines.append("")
    return "\n".join(lines)


def render_env_setup() -> str:
    return "\n".join(
        [
            "新手环境配置与国内镜像加速 / 按下面顺序做, 全程约 10 分钟",
            "",
            "[1] Python 3.9+",
            "  官网下载安装时勾选 Add Python to PATH.",
            "  验证: python --version",
            "  国内镜像: pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple",
            "  备用镜像: pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/",
            "  安装依赖: pip install -r requirements.txt",
            "",
            "[2] Node.js 18+ (仅前端/博客类专题需要)",
            "  验证: node -v && npm -v",
            "  国内镜像: npm config set registry https://registry.npmmirror.com",
            "",
            "[3] Java 17 + Maven (仅 Spring Boot 类专题需要)",
            "  验证: java -version && mvn -v",
            "  Maven 镜像: 在 ~/.m2/settings.xml 配置 aliyun maven mirror.",
            "",
            "[4] Git 与源码拉取",
            "  国内加速: git clone https://ghproxy.net/https://github.com/OWNER/REPO.git",
            "  或直接使用本合集 03 目录下的已解压源码, 无需再联网.",
            "",
            "[5] 常见问题",
            "  Q: pip 下载超时 -> 换阿里源, 或加 --timeout 60",
            "  Q: npm install 卡住 -> npm config get registry 确认已切国内源",
            "  Q: 端口被占用 -> 改 application.yml 的 server.port",
            "  Q: 缺 DLL / MSVCR -> 安装微软 VC++ 运行库合集",
            "  Q: 杀毒软件误报 -> 开源项目请自行核对源码后加入白名单",
            "",
            "[6] 目录导航",
            "  00_项目清单与中文简介说明.md  <- 当前这份清单的上一级说明",
            "  02_Windows免安装可执行程序包/  <- 已提取的 Release 安装包",
            "  03_精选开源项目源码合集/       <- 按编号排列的源码, 完整保留 LICENSE",
            "",
            "本文件会按买家高频咨询持续迭代, 每周往网盘文件夹追加更新.",
            "",
        ]
    )


def build_topic(
    topic: dict[str, Any],
    repos: list[Repo],
    archives: list[tuple[Repo, Path, dict[str, Any]]],
    release_files: dict[str, list[tuple[str, str]]],
    root: str | Path,
    engine_root: str | Path,
    cfg: dict[str, Any],
    excluded: list[dict[str, str]],
) -> dict[str, Any]:
    """组装一个专题包. archives 已由 cli 下载完成, 本函数只做解包与排版.

    增量保护 (策略书 6 第三阶段「每周往老文件夹追加新项目」):
      重建前先抢救两类人工/运营数据, 重建后原样回写:
        · 旧 _manifest.json 的 pan 段 (已 bind-pan 的推广链与报备状态)
        · 01 文件里「## 买家高频咨询补充」之后的段落 (售后迭代内容)
      否则一次 build 就会把已绑定渠道和 FAQ 一起删掉, 老买家链接直接失效.
    """
    dest = package_dir(root, str(topic["name"]))
    saved_pan: dict[str, Any] = {}
    saved_faq = ""
    if dest.exists():
        old_mf = dest / "_manifest.json"
        if old_mf.is_file():
            try:
                saved_pan = dict(json.loads(old_mf.read_text(encoding="utf-8")).get("pan") or {})
            except (json.JSONDecodeError, OSError):
                saved_pan = {}
        old_env = dest / "01_新手环境配置与国内镜像加速.txt"
        if old_env.is_file():
            old_text = old_env.read_text(encoding="utf-8")
            marker = "## 买家高频咨询补充"
            if marker in old_text:
                saved_faq = old_text.split(marker, 1)[1].strip()
        shutil.rmtree(dest)
    (dest / "02_Windows免安装可执行程序包").mkdir(parents=True, exist_ok=True)
    (dest / "03_精选开源项目源码合集").mkdir(parents=True, exist_ok=True)

    declaration = read_declaration(engine_root, cfg)
    declaration_issues = check_declaration(declaration)
    if declaration_issues:
        raise ValueError("合规声明校验失败: " + "; ".join(declaration_issues))

    rows: list[dict[str, Any]] = []
    for idx, (repo, tar_path, dl_meta) in enumerate(archives, start=1):
        folder = f"{idx:02d}_{safe_name(repo.full_name.replace('/', '_'))}"
        extract_info = extract_source(tar_path, dest / "03_精选开源项目源码合集" / folder)
        if not extract_info["license_files"]:
            raise ValueError("LICENSE 缺失, 拒绝收录: " + repo.full_name)
        assets: list[str] = []
        for src, name in release_files.get(repo.full_name, []):
            target = place_release_asset(src, dest / "02_Windows免安装可执行程序包", name)
            assets.append(Path(target).name)
        rows.append(
            {
                "index": f"{idx:02d}",
                "folder": folder,
                "full_name": repo.full_name,
                "html_url": repo.html_url,
                "description": repo.description,
                "stars": repo.stars,
                "pushed_at": repo.pushed_at,
                "license_key": repo.license_key,
                "license_name": repo.license_name,
                "topics": repo.topics,
                "archive_url": dl_meta.get("url", ""),
                "archive_sha256": dl_meta.get("sha256", ""),
                "archive_bytes": dl_meta.get("bytes", 0),
                "license_in_archive": ", ".join(extract_info["license_files"]),
                "release_assets": assets,
                "extract_rejected": extract_info["rejected_count"],
            }
        )

    intro = [str(p) for p in topic.get("intro", [])]
    (dest / "00_项目清单与中文简介说明.md").write_text(
        render_project_manifest(topic, rows, declaration, intro), encoding="utf-8", newline="\n"
    )
    env_text = render_env_setup()
    if saved_faq:
        env_text += "\n## 买家高频咨询补充\n\n" + saved_faq + "\n"
    (dest / "01_新手环境配置与国内镜像加速.txt").write_text(
        env_text, encoding="utf-8", newline="\n"
    )
    exe_dir = dest / "02_Windows免安装可执行程序包"
    if not any(exe_dir.iterdir()):
        (exe_dir / "README_本专题暂无Windows安装包.txt").write_text(
            "本专题收录项目均为源码工程, 暂无官方 Release Windows 安装包.\n"
            "请按 01_新手环境配置与国内镜像加速.txt 配好环境后, 进入 03 目录运行.\n",
            encoding="utf-8",
            newline="\n",
        )

    size_bytes = dir_size(dest)
    manifest = {
        "schema": "github-bundle-engine/manifest@1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "topic": {
            "id": topic["id"],
            "name": topic["name"],
            "price": topic["price"],
            "price_tier": topic["price_tier"],
            "audience": topic["audience"],
            "selling_point": topic["selling_point"],
            "intro": [str(p) for p in topic.get("intro", [])],
            "long_tail": [str(k) for k in topic.get("long_tail", [])],
        },
        "folder": dest.name,
        "package_bytes": size_bytes,
        "package_mb": round(size_bytes / 1024 / 1024, 2),
        "size_ok": bool(
            int(cfg.get("size_min_mb", 500)) * 1024 * 1024
            <= size_bytes
            <= int(cfg.get("size_max_mb", 2048)) * 1024 * 1024
        ),
        "repo_count": len(rows),
        "repos": rows,
        "excluded": excluded,
        "declaration": declaration,
        "pan": saved_pan or {
            "promote_uid_env": "PAN_PROMOTE_UID",
            "share_url": "",
            "extract_code": "",
            "channel_reported": False,
        },
    }
    if saved_pan:
        manifest["rebuild_preserved"] = {
            "pan": True,
            "buyer_faq": bool(saved_faq),
            "note": "本次重建沿用旧推广链与买家 FAQ, 老买家链接保持有效",
        }
    write_json_atomic(dest / "_manifest.json", manifest)
    return {"folder": str(dest), "manifest": manifest}
