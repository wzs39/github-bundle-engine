"""GitHub REST 客户端: 搜索 / Release 查询 / 源码与资产下载.

仅用 urllib 标准库. 处理 Search API 限流 (403/429 + X-RateLimit-Reset),
分页上限, 镜像前缀回退, 临时文件原子落盘与 SHA-256 校验.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

API_ROOT = "https://api.github.com"
USER_AGENT = "github-bundle-engine/1.0"
MAX_SEARCH_PAGES = 10


@dataclass
class Repo:
    full_name: str
    html_url: str
    description: str
    stars: int
    pushed_at: str
    default_branch: str
    license_key: str
    license_name: str
    topics: list[str] = field(default_factory=list)

    @classmethod
    def from_api(cls, raw: dict[str, Any]) -> "Repo":
        lic = raw.get("license") or {}
        return cls(
            full_name=str(raw.get("full_name") or ""),
            html_url=str(raw.get("html_url") or ""),
            description=str(raw.get("description") or "").strip(),
            stars=int(raw.get("stargazers_count") or 0),
            pushed_at=str(raw.get("pushed_at") or ""),
            default_branch=str(raw.get("default_branch") or "main"),
            license_key=str(lic.get("spdx_id") or "NOASSERTION"),
            license_name=str(lic.get("name") or ""),
            topics=[str(t) for t in (raw.get("topics") or [])],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "full_name": self.full_name,
            "html_url": self.html_url,
            "description": self.description,
            "stars": self.stars,
            "pushed_at": self.pushed_at,
            "default_branch": self.default_branch,
            "license_key": self.license_key,
            "license_name": self.license_name,
            "topics": self.topics,
        }


class GitHubError(RuntimeError):
    """调用链上可复现的失败, 带具体端点与原因."""


class GitHubClient:
    def __init__(
        self,
        token: str = "",
        api_root: str = API_ROOT,
        timeout: float = 30.0,
        max_retries: int = 4,
        min_interval: float = 2.0,
        mirrors: list[str] | None = None,
    ) -> None:
        self.token = token or os.environ.get("GITHUB_TOKEN", "")
        self.api_root = api_root.rstrip("/")
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.min_interval = min_interval
        self.mirrors = [m for m in (mirrors or []) if m and not m.startswith("[")]
        self._last_call = 0.0
        self.calls = 0

    def _headers(self) -> dict[str, str]:
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        return headers

    def _throttle(self) -> None:
        gap = time.monotonic() - self._last_call
        if gap < self.min_interval:
            time.sleep(self.min_interval - gap)
        self._last_call = time.monotonic()

    def _read(self, url: str, headers: dict[str, str]) -> tuple[bytes, dict[str, str]]:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read()
            meta = {k.lower(): v for k, v in resp.headers.items()}
            return raw, meta

    def _get_json(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params)
        url = self.api_root + path + "?" + query
        last = "unknown"
        for attempt in range(self.max_retries):
            self._throttle()
            self.calls += 1
            try:
                raw, _ = self._read(url, self._headers())
                return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                last = "HTTP " + str(exc.code)
                remaining = exc.headers.get("X-RateLimit-Remaining")
                reset = exc.headers.get("X-RateLimit-Reset")
                if exc.code in (403, 429) and remaining == "0" and reset:
                    wait = max(1.0, float(reset) - time.time() + 2.0)
                    wait = min(wait, 90.0)
                    time.sleep(wait)
                    continue
                if exc.code in (403, 429, 502, 503):
                    time.sleep(min(2.0 * (attempt + 1), 12.0))
                    continue
                if exc.code == 404:
                    raise GitHubError("404 " + path)
                raise GitHubError(last + " on " + path)
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last = repr(exc)
                time.sleep(min(2.0 * (attempt + 1), 12.0))
                continue
        raise GitHubError("重试耗尽 " + path + " / " + last)

    @staticmethod
    def pushed_after(days: int) -> str:
        stamp = datetime.now(timezone.utc) - timedelta(days=days)
        return stamp.strftime("%Y-%m-%d")

    def search(self, query: str, min_stars: int, pushed_after_days: int, limit: int) -> list[Repo]:
        q = query.strip() + " stars:>=" + str(min_stars)
        q += " pushed:>=" + self.pushed_after(pushed_after_days)
        q += " archived:false fork:false"
        found: list[Repo] = []
        for page in range(1, MAX_SEARCH_PAGES + 1):
            need = min(100, limit - len(found))
            if need <= 0:
                break
            data = self._get_json(
                "/search/repositories",
                {"q": q, "sort": "stars", "order": "desc", "per_page": need, "page": page},
            )
            items = data.get("items") or []
            if not items:
                break
            found.extend(Repo.from_api(item) for item in items)
            if len(items) < need:
                break
        return found[:limit]

    def latest_release_assets(self, full_name: str) -> list[dict[str, Any]]:
        try:
            data = self._get_json("/repos/" + full_name + "/releases/latest", {})
        except GitHubError:
            return []
        assets = data.get("assets") or []
        return [
            {
                "name": str(a.get("name") or ""),
                "url": str(a.get("browser_download_url") or ""),
                "size": int(a.get("size") or 0),
                "download_count": int(a.get("download_count") or 0),
            }
            for a in assets
        ]

    def source_url(self, repo: Repo) -> str:
        return (
            "https://codeload.github.com/" + repo.full_name + "/tar.gz/refs/heads/"
            + urllib.parse.quote(repo.default_branch, safe="")
        )

    def download(self, url: str, dest: Path) -> dict[str, Any]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        candidates = [url]
        for mirror in self.mirrors:
            candidates.append(mirror.rstrip("/") + "/" + url)
        last = "no candidate"
        for target in candidates:
            try:
                self._throttle()
                req = urllib.request.Request(
                    target, headers={"User-Agent": USER_AGENT, "Accept": "*/*"}
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    tmp = dest.with_name(dest.name + ".part")
                    digest = hashlib.sha256()
                    total = 0
                    with tmp.open("wb") as fh:
                        while True:
                            chunk = resp.read(1 << 20)
                            if not chunk:
                                break
                            fh.write(chunk)
                            digest.update(chunk)
                            total += len(chunk)
                    tmp.replace(dest)
                    return {
                        "url": target,
                        "path": str(dest),
                        "sha256": digest.hexdigest(),
                        "bytes": total,
                    }
            except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
                last = repr(exc)
                continue
        raise GitHubError("下载失败 " + url + " / " + last)
