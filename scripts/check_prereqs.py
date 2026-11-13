"""开工前自检: 按 docs/PREREQUISITES.md 逐项打印「已就绪 / 待补」.

用法: python scripts/check_prereqs.py [--out OUTPUT_DIR] [--json]
全程只读, 不联网, 不修改任何文件, 不打印任何凭据明文.
退出码: 0 = A 类硬门槛全过; 1 = 仍有待补项 (仅提示, 不阻塞离线 selftest).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ENGINE_ROOT = Path(__file__).resolve().parent.parent
TOPIC_IDS = ("local-ai", "py-office", "grad-project", "portfolio")
PLACEHOLDER = "["

SECRETS = ("GITHUB_TOKEN", "PAN_PROMOTE_UID", "XIANYU_AUTO_REPLY_PLUGIN")


def _load_dotenv() -> None:
    """与 run_daily.ps1 对齐: 本地 .env 存在时加载进环境 (不覆盖已有值).

    否则 .env 已填好、计划任务能跑, 自检却永远报 WAIT, 误导判断.
    """
    env_path = ENGINE_ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if key in SECRETS and value and not os.environ.get(key, "").strip():
            os.environ[key] = value


def _env_ready(key: str) -> tuple[bool, str]:
    value = os.environ.get(key, "").strip()
    if not value:
        return False, "环境变量未设置"
    if value.startswith(PLACEHOLDER):
        return False, "仍是占位值"
    return True, "已设置 (长度 " + str(len(value)) + ", 明文不回显)"


def _load_settings() -> dict[str, Any]:
    path = ENGINE_ROOT / "config" / "settings.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _manifests(root: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(root.glob("2026持续更新_*合集/_manifest.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        tid = str((data.get("topic") or {}).get("id") or "")
        if tid:
            out[tid] = data
    return out


def _gh_login() -> tuple[bool, str]:
    exe = shutil.which("gh")
    if not exe:
        return False, "未安装 gh"
    try:
        p = subprocess.run(
            [exe, "api", "user", "--jq", ".login"],
            capture_output=True,
            timeout=15,
        )
        login = (p.stdout or b"").decode("utf-8", "replace").strip()
        return (p.returncode == 0 and bool(login)), ("已登录 " + login if login else "未登录")
    except (OSError, subprocess.SubprocessError):
        return False, "gh 调用失败"


def check(out_dir: str) -> dict[str, Any]:
    root = Path(out_dir)
    if not root.is_absolute():
        root = (ENGINE_ROOT / root).resolve()
    settings = _load_settings()
    manifests = _manifests(root)
    gh_ok, gh_note = _gh_login()

    a: list[dict[str, Any]] = []

    token_ok, token_note = _env_ready("GITHUB_TOKEN")
    a.append({
        "id": "A1", "name": "GITHUB_TOKEN (真实抓取)",
        "ok": token_ok, "note": token_note,
        "how": "GitHub Settings -> Developer settings -> PAT (public_repo 只读) -> 设环境变量",
    })

    # 夹具域名 (.test / example) 与方括号占位符都不算真实推广链,
    # 否则本地测试残留会让自检误报「已绑定」.
    fake_markers = (".test", "example", "[PAN_", "pan.example", "localhost", "127.0.0.1")
    bound: dict[str, bool] = {}
    for tid in TOPIC_IDS:
        url = str((manifests.get(tid, {}).get("pan") or {}).get("share_url") or "")
        bound[tid] = bool(url) and not any(m in url.lower() for m in fake_markers)
    uid_ok, uid_note = _env_ready("PAN_PROMOTE_UID")
    pan_ok = all(bound.values()) and uid_ok
    a.append({
        "id": "A2", "name": "网盘推广链 + 报备 UID",
        "ok": pan_ok,
        "note": "真实绑定 " + str(sum(bound.values())) + "/4; " + uid_note,
        "detail": {k: ("已绑定" if v else "待 bind-pan") for k, v in bound.items()},
        "how": "服务商后台报备夸克+百度网盘 -> 生成推广链 -> bind-pan --topic <id> --share-url ... --extract-code ...",
    })

    real_repos = any(
        any(not str(r.get("full_name", "")).startswith("fixture-") for r in (m.get("repos") or []))
        for m in manifests.values()
    )
    size_ok = bool(manifests) and all(m.get("size_ok") for m in manifests.values())
    a.append({
        "id": "A3", "name": "真实抓取 build --all",
        "ok": real_repos and size_ok,
        "note": ("真实仓库: " + ("是" if real_repos else "否") + "; 体积达标: " + ("是" if size_ok else "否")),
        "how": "set GITHUB_TOKEN=[...] 后 python -m src.cli build --all --out OUTPUT_DIR",
    })

    plugin_ok, plugin_note = _env_ready("XIANYU_AUTO_REPLY_PLUGIN")
    a.append({
        "id": "A4", "name": "闲鱼独立号 + 自动发货插件",
        "ok": plugin_ok, "note": plugin_note + " (实名/养号需人工完成, 脚本只查插件标识)",
        "how": "独立号实名+芝麻授权, 养号 2 天, 网页版后台自动回复粘 listings/<id>/auto_reply.txt",
    })

    packages = sorted(root.glob("2026持续更新_*合集"))
    a.append({
        "id": "A5", "name": "网盘整目录上传",
        "ok": False,
        "note": "本地有 " + str(len(packages)) + " 个多级目录; 上传动作在网盘客户端, 脚本无法核验",
        "how": "把 00/01/02/03 整目录上传到 A2 的推广 UID 名下, 不压死压缩包",
        "manual": True,
    })

    mirrors = [m for m in (settings.get("download_mirrors") or []) if not str(m).startswith(PLACEHOLDER)]
    b: list[dict[str, Any]] = [
        {
            "id": "B1", "name": "codeload 镜像回退前缀",
            "ok": bool(mirrors), "note": "可用前缀 " + str(len(mirrors)) + " 个",
            "how": "config/settings.json 的 download_mirrors 填真实加速前缀",
        },
        {
            "id": "B2", "name": "PAN_PROMOTE_UID",
            "ok": uid_ok, "note": uid_note,
            "how": "环境变量 PAN_PROMOTE_UID=[已报备 UID]",
        },
        {
            "id": "B3", "name": "主图素材",
            "ok": False, "note": "listing_plan.json 只给文字规格, 需人工出图",
            "how": "目录截图 + 痛点大字, 每专题 1 张; 爆款另做 1-2 张衍生封面",
            "manual": True,
        },
    ]

    d: list[dict[str, Any]] = [
        {"id": "D1", "name": "Python", "ok": sys.version_info >= (3, 9), "note": sys.version.split()[0]},
        {"id": "D2", "name": "GitHub CLI", "ok": gh_ok, "note": gh_note},
        {"id": "D3", "name": "离线闭环", "ok": (ENGINE_ROOT / "src" / "cli.py").is_file(), "note": "selftest / verify / schedule / report 可用"},
        {"id": "D4", "name": "回归测试", "ok": (ENGINE_ROOT / "tests" / "test_engine.py").is_file(), "note": "56 项离线回归"},
    ]

    hard_pending = [x["id"] for x in a if not x["ok"] and not x.get("manual")]
    return {
        "schema": "github-bundle-engine/prereqs@1",
        "out_dir": str(root),
        "A_hard": a,
        "B_placeholders": b,
        "D_ready": d,
        "hard_pending": hard_pending,
        "manual_pending": [x["id"] for x in a + b if x.get("manual") or (not x["ok"] and x["id"] in ("A4", "A5", "B3"))],
        "can_sell": not hard_pending,
        "hint": "docs/PREREQUISITES.md 有每一项的详细说明与验收命令",
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="开工前自检 (只读, 不联网, 不回显凭据)")
    ap.add_argument("--out", default="OUTPUT_DIR")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    _load_dotenv()
    result = check(args.out)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["can_sell"] else 1

    def line(item: dict[str, Any]) -> str:
        mark = "OK  " if item["ok"] else "WAIT"
        manual = " [人工]" if item.get("manual") else ""
        return "  [" + mark + "] " + item["id"] + " " + item["name"] + manual + " - " + str(item["note"])

    print("开工前自检 · " + str(result["out_dir"]))
    print("A 类硬门槛:")
    for x in result["A_hard"]:
        print(line(x))
    print("B 类占位值:")
    for x in result["B_placeholders"]:
        print(line(x))
    print("D 类已具备:")
    for x in result["D_ready"]:
        print(line(x))
    print("")
    print("硬门槛待补: " + (", ".join(result["hard_pending"]) or "无"))
    print("人工动作待办: " + (", ".join(sorted(set(result["manual_pending"]))) or "无"))
    print("能否开始卖: " + ("是" if result["can_sell"] else "否"))
    print("详见 " + result["hint"])
    return 0 if result["can_sell"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
