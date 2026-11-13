"""离线回归测试: 合规闸 / 解包 / 打包 / 文案 / 收益模型 / selftest 主流程.

运行: python -m unittest discover -s tests -v
全程不联网, 不依赖第三方库.
"""
from __future__ import annotations

import io
import json
import sys
import tarfile
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ENGINE_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGINE_ROOT))

from src import cli  # noqa: E402
from src.compliance import (  # noqa: E402
    check_declaration,
    check_text,
    has_license,
    load_config,
    read_declaration,
    screen_repo,
    select_release_assets,
)
from src.downloader import extract_source  # noqa: E402
from src.gh_client import Repo  # noqa: E402
from src.listing import (  # noqa: E402
    render_auto_reply,
    render_detail,
    render_listing_plan,
    render_title,
)
from src.packer import safe_name, render_project_manifest  # noqa: E402
from src.pan import bind as bind_pan  # noqa: E402
from src.pan import find_manifests, validate_extract_code, validate_share_url  # noqa: E402
from src.scheduler import build_schedule, rotate_keywords, render_schedule_md  # noqa: E402
from scripts import economics  # noqa: E402

CFG = load_config(ENGINE_ROOT / "config" / "compliance.json")
TOPICS = load_config(ENGINE_ROOT / "config" / "topics.json")


def repo(**kw: object) -> Repo:
    base = dict(
        full_name="acme/useful-tool",
        html_url="https://github.com/acme/useful-tool",
        description="A useful open source automation tool",
        stars=5000,
        pushed_at="2026-08-01T00:00:00Z",
        default_branch="main",
        license_key="MIT",
        license_name="MIT License",
        topics=["automation"],
    )
    base.update(kw)
    return Repo(**base)  # type: ignore[arg-type]


def make_tar(path: Path, entries: dict[str, bytes], mtime: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(path, "w:gz") as tf:
        for name, payload in entries.items():
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            info.mtime = mtime or int(time.time())
            info.mode = 0o644
            tf.addfile(info, io.BytesIO(payload))


class TestScreenRepo(unittest.TestCase):
    def test_clean_repo_passes(self) -> None:
        ok, reason = screen_repo(repo(), CFG)
        self.assertTrue(ok, reason)

    def test_block_term_rejects(self) -> None:
        ok, reason = screen_repo(repo(description="a pentest toolkit"), CFG)
        self.assertFalse(ok)
        self.assertIn("黑名单", reason)

    def test_block_topic_rejects(self) -> None:
        ok, reason = screen_repo(repo(topics=["vpn"]), CFG)
        self.assertFalse(ok)
        self.assertIn("topic", reason)

    def test_license_whitelist_rejects(self) -> None:
        ok, reason = screen_repo(repo(license_key="NOASSERTION"), CFG)
        self.assertFalse(ok)
        self.assertIn("协议", reason)

    def test_zero_star_rejects(self) -> None:
        ok, _ = screen_repo(repo(stars=0), CFG)
        self.assertFalse(ok)


class TestReleaseAssets(unittest.TestCase):
    def test_filters_by_ext_and_size(self) -> None:
        assets = [
            {"name": "setup.exe", "url": "https://x/setup.exe", "size": 10 * 1024 * 1024},
            {"name": "source.tar.gz", "url": "https://x/source.tar.gz", "size": 1024},
            {"name": "huge.msi", "url": "https://x/huge.msi", "size": 500 * 1024 * 1024},
            {"name": "ok.zip", "url": "https://x/ok.zip", "size": 2048},
        ]
        picked = select_release_assets(assets, CFG)
        self.assertEqual([a["name"] for a in picked], ["setup.exe", "ok.zip"])

    def test_rejects_contact_in_name(self) -> None:
        assets = [{"name": "加微信领安装包.exe", "url": "https://x/a.exe", "size": 1024}]
        self.assertEqual(select_release_assets(assets, CFG), [])


class TestLicenseAndExtract(unittest.TestCase):
    def test_license_found_in_archive(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.tar.gz"
            make_tar(p, {"repo-main/LICENSE": b"MIT\n", "repo-main/src/a.py": b"x=1\n"})
            ok, hit = has_license(p, CFG)
            self.assertTrue(ok)
            self.assertIn("LICENSE", hit)

    def test_license_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "a.tar.gz"
            make_tar(p, {"repo-main/README.md": b"hi\n"})
            ok, reason = has_license(p, CFG)
            self.assertFalse(ok)
            self.assertIn("未找到", reason)

    def test_path_traversal_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            p = base / "evil.tar.gz"
            make_tar(
                p,
                {
                    "root/../escape.txt": b"bad\n",
                    "root/LICENSE": b"MIT\n",
                    "root/src/main.py": b"print(1)\n",
                },
            )
            out = base / "out"
            info = extract_source(p, out)
            self.assertEqual(info["files"], 2)
            self.assertFalse((base / "escape.txt").exists())
            self.assertEqual(info["rejected_count"], 1)

    def test_symlink_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            p = base / "link.tar.gz"
            with tarfile.open(p, "w:gz") as tf:
                link = tarfile.TarInfo("root/link")
                link.type = tarfile.SYMTYPE
                link.linkname = "../../etc/passwd"
                tf.addfile(link)
                normal = tarfile.TarInfo("root/LICENSE")
                payload = b"MIT\n"
                normal.size = len(payload)
                tf.addfile(normal, io.BytesIO(payload))
            info = extract_source(p, base / "out")
            self.assertEqual(info["rejected_count"], 1)
            self.assertEqual(info["license_files"], ["LICENSE"])


class TestTextCompliance(unittest.TestCase):
    def test_declaration_from_file_passes(self) -> None:
        text = read_declaration(ENGINE_ROOT, CFG)
        self.assertTrue(text)
        self.assertEqual(check_declaration(text), [])

    def test_contact_rejected(self) -> None:
        for bad in ("加微信 abc123 领资料", "联系 QQ号 10086", "扫码进群看二维码", "手机号 13800138000"):
            with self.subTest(bad=bad):
                self.assertTrue(check_text(bad))

    def test_forced_app_rejected(self) -> None:
        self.assertTrue(check_text("必须下载某 App 才能发货"))

    def test_zero_width_rejected(self) -> None:
        self.assertTrue(check_text("正常文本" + chr(0x200B) + "尾部"))

    def test_clean_text_passes(self) -> None:
        self.assertEqual(check_text("资源已整理存入网盘, 建议保存至个人网盘后按需下载"), [])

    def test_missing_declaration_detected(self) -> None:
        self.assertTrue(check_declaration("随便一句资源说明"))


class TestListing(unittest.TestCase):
    def setUp(self) -> None:
        self.topic = TOPICS["topics"][1]
        self.declaration = read_declaration(ENGINE_ROOT, CFG)
        self.manifest = {
            "repo_count": 12,
            "package_mb": 780.5,
            "folder": "2026持续更新_GitHub精选【Python办公自动化神器】合集",
        }

    def test_detail_clean_and_contains_declaration(self) -> None:
        text = render_detail(self.topic, self.manifest, self.declaration)
        self.assertEqual(check_text(text), [])
        self.assertIn("所收费用仅为", text)

    def test_auto_reply_clean(self) -> None:
        text = render_auto_reply(self.topic, "[PAN_SHARE_URL]", "[PAN_EXTRACT_CODE]")
        self.assertEqual(check_text(text), [])
        self.assertIn("[PAN_SHARE_URL]", text)
        self.assertNotIn("必须下载", text)

    def test_title_length(self) -> None:
        self.assertLessEqual(len(render_title(self.topic)), 60)

    def test_plan_stock_and_interval(self) -> None:
        plan = render_listing_plan(self.topic, self.manifest)
        self.assertEqual(plan["stock_min"], 50)
        self.assertEqual(plan["stock_max"], 99)
        self.assertEqual(plan["listing_interval_minutes"], 60)
        self.assertIn("曝光 < 100", plan["retire_rule"])


class TestEconomics(unittest.TestCase):
    def test_blend_price_in_range(self) -> None:
        p = economics.blend_price()
        self.assertGreater(p, 0.99)
        self.assertLess(p, 9.9)

    def test_scenario_math(self) -> None:
        s = economics.Scenario("t", 20, 10, 4.0, 4, 30)
        self.assertEqual(s.front, 40.0)
        self.assertEqual(s.pan_low, 4 * 7.0 + 30 * 0.3)
        self.assertEqual(s.pan_high, 4 * 12.0 + 30 * 0.5)
        self.assertEqual(s.to_dict()["total_low"], 40.0 + 28.0 + 9.0)


class TestSafeName(unittest.TestCase):
    def test_ascii_and_chinese(self) -> None:
        self.assertEqual(safe_name("Python 办公/自动化"), "Python_办公_自动化")

    def test_empty_fallback(self) -> None:
        self.assertEqual(safe_name("!!!"), "unnamed")


class TestSelfTestCommand(unittest.TestCase):
    def test_selftest_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            rc = cli.main(["selftest", "--out", td])
            self.assertEqual(rc, 0)
            packs = list(Path(td).glob("2026持续更新_*合集/_manifest.json"))
            self.assertEqual(len(packs), 1)
            data = json.loads(packs[0].read_text(encoding="utf-8"))
            self.assertEqual(data["repo_count"], 3)
            self.assertTrue(all(r["license_in_archive"] for r in data["repos"]))
            reply = Path(td) / "listings" / "local-ai" / "auto_reply.txt"
            self.assertTrue(reply.is_file())
            self.assertEqual(check_text(reply.read_text(encoding="utf-8")), [])
            self.assertTrue((Path(td) / "reports" / "selftest_daily.json").is_file())

    def test_verify_on_selftest_output(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cli.main(["selftest", "--out", td]), 0)
            self.assertEqual(cli.main(["verify", "--out", td]), 0)

    def test_selftest_all_topics(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cli.main(["selftest", "--all-topics", "--out", td]), 0)
            packs = list(Path(td).glob("2026持续更新_*合集/_manifest.json"))
            self.assertEqual(len(packs), 4)
            for mf in packs:
                data = json.loads(mf.read_text(encoding="utf-8"))
                self.assertTrue(data["topic"]["intro"], mf.name)
                doc = (mf.parent / "00_项目清单与中文简介说明.md").read_text(encoding="utf-8")
                self.assertIn("## 这套合集解决什么", doc)
            self.assertEqual(cli.main(["verify", "--out", td]), 0)


class TestIntro(unittest.TestCase):
    def test_all_topics_have_three_paragraphs(self) -> None:
        for topic in TOPICS["topics"]:
            with self.subTest(topic=topic["id"]):
                self.assertEqual(len(topic["intro"]), 3)
                self.assertTrue(all(len(p) > 30 for p in topic["intro"]))

    def test_intro_renders_into_manifest(self) -> None:
        topic = TOPICS["topics"][1]
        text = render_project_manifest(topic, [], "声明占位", topic["intro"])
        self.assertIn("## 这套合集解决什么", text)
        self.assertIn(topic["intro"][0], text)
        self.assertIn("声明占位", text)

    def test_intro_without_paragraphs_has_fallback(self) -> None:
        text = render_project_manifest(TOPICS["topics"][1], [], "声明占位", [])
        self.assertIn("按业务场景归类", text)


class TestPan(unittest.TestCase):
    def test_share_url_rejects_placeholder_and_contact(self) -> None:
        self.assertTrue(validate_share_url("[PAN_SHARE_URL]"))
        self.assertTrue(validate_share_url("ftp://pan.example.test/s/a"))
        self.assertTrue(validate_share_url("https://pan.example.test/s/a?wx=abc"))
        self.assertEqual(validate_share_url("https://pan.example.test/s/a"), [])

    def test_extract_code_rejects_placeholder(self) -> None:
        self.assertTrue(validate_extract_code("[PAN_EXTRACT_CODE]"))
        self.assertEqual(validate_extract_code("8f2k"), [])

    def test_bind_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cli.main(["selftest", "--all-topics", "--out", td]), 0)
            self.assertEqual(
                cli.main([
                    "bind-pan", "--topic", "py-office",
                    "--share-url", "https://pan.example.test/s/abc123",
                    "--extract-code", "8f2k",
                    "--promote-uid", "[PAN_PROMOTE_UID]", "--out", td,
                ]),
                0,
            )
            path = find_manifests(td)["py-office"]
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["pan"]["share_url"], "https://pan.example.test/s/abc123")
            self.assertTrue(data["pan"]["channel_reported"])
            reply = (Path(td) / "listings" / "py-office" / "auto_reply.txt").read_text(encoding="utf-8")
            self.assertIn("https://pan.example.test/s/abc123", reply)
            self.assertEqual(check_text(reply), [])
            self.assertEqual(cli.main(["verify", "--out", td]), 0)

    def test_bind_rejects_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cli.main(["selftest", "--out", td]), 0)
            rc = cli.main([
                "bind-pan", "--topic", "local-ai",
                "--share-url", "[PAN_SHARE_URL]", "--extract-code", "[CODE]", "--out", td,
            ])
            self.assertEqual(rc, 1)


class TestScheduler(unittest.TestCase):
    def setUp(self) -> None:
        self.topics = TOPICS["topics"]
        self.manifests = {
            t["id"]: {
                "topic": {"id": t["id"], "name": t["name"], "price": t["price"],
                          "selling_point": t["selling_point"], "long_tail": t["long_tail"]},
                "folder": "demo", "package_mb": 800, "repo_count": 10,
                "pan": {},
            }
            for t in self.topics
        }

    def test_rotate_keywords_no_repeat_inside_one_slot(self) -> None:
        pool = ["a", "b", "c", "d"]
        for seq in range(12):
            kws = rotate_keywords(pool, seq)
            self.assertEqual(len(kws), len(set(kws)))

    def test_rotate_keywords_cycles_every_round(self) -> None:
        pool = ["a", "b", "c", "d"]
        rounds = [tuple(rotate_keywords(pool, i)) for i in range(4)]
        self.assertEqual(len(set(rounds)), 4, "4 个专题 x 3 词时不能撞回同一组")

    def test_interval_and_link_cap(self) -> None:
        sched = build_schedule(
            self.topics, self.manifests,
            datetime(2026, 9, 17, 9, 0), days=7, per_day=2,
            interval_minutes=60, existing_links=4,
        )
        self.assertEqual(len(sched["slots"]), 14)
        self.assertTrue(all(s["interval_minutes"] == 60 and s["gap_ok"] for s in sched["slots"]))
        self.assertLessEqual(sched["shelf"]["final_links"], 25)
        self.assertTrue(sched["shelf"]["in_target"])

    def test_interval_below_60_rejected(self) -> None:
        with self.assertRaises(ValueError):
            build_schedule(self.topics, self.manifests, datetime(2026, 9, 17, 9, 0), interval_minutes=30)

    def test_unbound_topics_flagged(self) -> None:
        sched = build_schedule(self.topics, self.manifests, datetime(2026, 9, 17, 9, 0), days=1)
        self.assertTrue(all("待补" in s["notes"] for s in sched["slots"]))

    def test_markdown_contains_sop(self) -> None:
        sched = build_schedule(self.topics, self.manifests, datetime(2026, 9, 17, 9, 0), days=1)
        md = render_schedule_md(sched)
        self.assertIn("闲鱼上架排程", md)
        self.assertIn("每日 90 分钟 SOP", md)
        self.assertIn("淘汰线", md)

    def test_schedule_command_writes_files(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(cli.main(["selftest", "--all-topics", "--out", td]), 0)
            self.assertEqual(
                cli.main([
                    "schedule", "--start", "2026-09-17T09:00:00",
                    "--days", "7", "--existing-links", "4", "--out", td,
                ]),
                0,
            )
            base = Path(td) / "reports"
            self.assertTrue((base / "schedule_2026-09-17.json").is_file())
            self.assertTrue((base / "schedule_2026-09-17.md").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
