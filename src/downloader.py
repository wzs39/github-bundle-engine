"""安全解包: tar 条目白名单 + 路径穿越防护 + 体积/数量上限.

策略书 3 要求「不压成单个死压缩包, 直接上传解压后的多级目录」,
本模块负责把 GitHub tarball 展开成可预览的多级目录, 并完整保留 LICENSE.
"""
from __future__ import annotations

import json
import shutil
import tarfile
from pathlib import Path, PurePosixPath
from typing import Any

MAX_ENTRIES = 20000
MAX_TOTAL_BYTES = 2 * 1024 * 1024 * 1024
SKIP_SUFFIXES = (".exe", ".msi", ".dmg", ".so", ".dll", ".pyd", ".class", ".jar")


def _safe_member(member: tarfile.TarInfo) -> bool:
    name = member.name
    if not name or name.startswith("/") or "\\" in name:
        return False
    parts = PurePosixPath(name).parts
    if any(p in ("", ".", "..") for p in parts):
        return False
    if member.issym() or member.islnk() or member.isdev() or member.isfifo():
        return False
    if member.isfile() and member.size > MAX_TOTAL_BYTES:
        return False
    return True


def extract_source(tar_path: str | Path, dest_dir: str | Path) -> dict[str, Any]:
    """把归档展开到 dest_dir. 返回统计与剔除记录."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written = 0
    total = 0
    rejected: list[str] = []
    license_hits: list[str] = []
    with tarfile.open(tar_path, "r:*") as tf:
        members = tf.getmembers()
        if len(members) > MAX_ENTRIES:
            rejected.append("条目数超上限 " + str(len(members)))
        root_names = {PurePosixPath(m.name).parts[0] for m in members if m.name}
        strip_root = len(root_names) == 1
        for member in members[:MAX_ENTRIES]:
            if not _safe_member(member):
                rejected.append(member.name)
                continue
            rel = PurePosixPath(member.name)
            parts = rel.parts[1:] if strip_root else rel.parts
            if not parts:
                continue
            target = dest.joinpath(*parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                rejected.append(member.name)
                continue
            if total + member.size > MAX_TOTAL_BYTES:
                rejected.append("总体积超上限: " + member.name)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            src = tf.extractfile(member)
            if src is None:
                rejected.append(member.name)
                continue
            with src, target.open("wb") as out:
                while True:
                    buf = src.read(1 << 20)
                    if not buf:
                        break
                    out.write(buf)
            base = target.name.upper()
            if base.startswith("LICENSE") or base.startswith("COPYING") or base.startswith("LICENCE"):
                license_hits.append(str(target.relative_to(dest)))
            written += 1
            total += member.size
    return {
        "dest": str(dest),
        "files": written,
        "bytes": total,
        "rejected_count": len(rejected),
        "rejected_sample": rejected[:20],
        "license_files": license_hits,
        "strip_root": strip_root,
    }


def place_release_asset(src: str | Path, dest_dir: str | Path, name: str) -> str:
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    target = dest / Path(name).name
    shutil.copyfile(src, target)
    return str(target)


def dir_size(path: str | Path) -> int:
    root = Path(path)
    total = 0
    for item in root.rglob("*"):
        if item.is_file():
            total += item.stat().st_size
    return total


def write_json_atomic(path: str | Path, payload: dict[str, Any]) -> None:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="\n") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=False)
        fh.write("\n")
    tmp.replace(dest)
