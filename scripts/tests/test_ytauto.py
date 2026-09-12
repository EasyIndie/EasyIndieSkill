#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ytauto 离线测试（标准库 unittest，绝不联网 / 绝不上传）。

运行::

    cd /Users/bot/.hermes/skills/media/easyindie
    python3 -m unittest discover -s scripts/tests -v

覆盖：账号 YAML 解析（含极简解析器）、meta 构造/校验、台账（含并发）、
退出码，以及用 fake_youtubeuploader.sh 的离线 E2E。所有临时数据都在 tmpdir，
绝不触碰真实 ``~/.hermes/youtube``。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TESTS_DIR.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from lib import ytauto_accounts as A  # noqa: E402
from lib import ytauto_ledger as L  # noqa: E402
from lib import ytauto_meta as M  # noqa: E402

STUB = TESTS_DIR / "stubs" / "fake_youtubeuploader.sh"
UPLOAD_PY = SCRIPTS_DIR / "youtube_upload.py"
ENV_KEYS = ("YT_ACCOUNTS_DIR", "YT_LEDGER", "YOUTUBE_DIR", "YT_ACCOUNT", "YT_UPLOADER")


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        os.environ["YOUTUBE_DIR"] = str(self.tmp / "yt")
        os.environ["YT_ACCOUNTS_DIR"] = str(self.tmp / "accounts")
        os.environ["YT_LEDGER"] = str(self.tmp / "ledger.csv")
        os.environ.pop("YT_ACCOUNT", None)
        os.environ.pop("YT_UPLOADER", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def write_account(self, name, token=True, secrets=True, **fields):
        adir = Path(os.environ["YT_ACCOUNTS_DIR"]) / name
        adir.mkdir(parents=True, exist_ok=True)
        lines = ["name: %s" % name]
        for k, v in fields.items():
            if isinstance(v, list):
                lines.append("%s: [%s]" % (k, ", ".join(str(x) for x in v)))
            else:
                lines.append("%s: %s" % (k, v))
        (adir / "account.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")
        if token:
            (adir / "request.token").write_text('{"refresh_token": "x"}', encoding="utf-8")
        if secrets:
            yt = Path(os.environ["YOUTUBE_DIR"])
            yt.mkdir(parents=True, exist_ok=True)
            (yt / "video_uploader.json").write_text(
                '{"installed": {"client_id": "x", "client_secret": "y"}}', encoding="utf-8")
        return adir

    def sub_env(self):
        env = dict(os.environ)
        env["YT_UPLOADER"] = str(STUB)
        return env


# --------------------------------------------------------------------------- #
class MiniYamlTest(Base):
    def test_scalars_and_inline_list(self):
        d = A._mini_yaml(
            "name: foo\n"
            "cap: 5\n"
            "flag: true\n"
            "tags: [a, b, \"c d\"]   # trailing comment\n"
            "empty: []\n"
        )
        self.assertEqual(d["name"], "foo")
        self.assertEqual(d["cap"], 5)
        self.assertIs(d["flag"], True)
        self.assertEqual(d["tags"], ["a", "b", "c d"])
        self.assertEqual(d["empty"], [])

    def test_block_list_and_block_scalar(self):
        d = A._mini_yaml(
            "playlists:\n"
            "  - asmr\n"
            "  - relax\n"
            "desc: |\n"
            "  line1\n"
            "  line2\n"
            "note: done\n"
        )
        self.assertEqual(d["playlists"], ["asmr", "relax"])
        self.assertEqual(d["desc"], "line1\nline2\n")
        self.assertEqual(d["note"], "done")

    def test_comment_and_quoted_hash(self):
        d = A._mini_yaml("a: value  # comment\nb: \"x # y\"\n")
        self.assertEqual(d["a"], "value")
        self.assertEqual(d["b"], "x # y")

    def test_one_level_dict(self):
        d = A._mini_yaml("extra:\n  madeForKids: false\n  embeddable: true\n")
        self.assertEqual(d["extra"], {"madeForKids": False, "embeddable": True})


class AccountsTest(Base):
    def test_load_account_fields(self):
        self.write_account(
            "alpha", display="Alpha TV", channel_id="UCplaceholder0000000000",
            default_privacy="private", default_language="en", default_category=22,
            default_playlists=["asmr", "relax"], tags_pool=["t1", "t2"],
            daily_publish_cap=7, doc_status="live", extra='{}',
        )
        acct = A.load_account("alpha")
        self.assertEqual(acct.name, "alpha")
        self.assertEqual(acct.display, "Alpha TV")
        self.assertEqual(acct.default_privacy, "private")
        self.assertEqual(acct.default_category, 22)
        self.assertEqual(acct.default_playlists, ["asmr", "relax"])
        self.assertEqual(acct.tags_pool, ["t1", "t2"])
        self.assertEqual(acct.daily_publish_cap, 7)
        self.assertTrue(str(acct.token_file).endswith("alpha/request.token"))

    def test_load_missing_raises(self):
        with self.assertRaises(A.AccountNotFound):
            A.load_account("nope")

    def test_resolve_default_env_and_sorted(self):
        self.write_account("zeta")
        self.write_account("alpha")
        self.assertEqual(A.resolve_default().name, "alpha")
        os.environ["YT_ACCOUNT"] = "zeta"
        self.assertEqual(A.resolve_default().name, "zeta")

    def test_resolve_default_empty_raises(self):
        with self.assertRaises(A.AccountNotFound):
            A.resolve_default()

    def test_init_account_no_overwrite(self):
        path = A.init_account("beta", template_values={"display": "Beta"})
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("display: Beta", text)
        with self.assertRaises(FileExistsError):
            A.init_account("beta", template_values={"display": "Changed"})
        self.assertEqual(path.read_text(encoding="utf-8"), text)

    def test_migrate_legacy_idempotent(self):
        yt = Path(os.environ["YOUTUBE_DIR"])
        yt.mkdir(parents=True, exist_ok=True)
        (yt / "request.token").write_text('{"refresh_token": "legacy"}', encoding="utf-8")
        r1 = A.migrate_legacy(target_name="alpha")
        self.assertTrue(r1["migrated"])
        legacy = yt / "request.token"
        target = Path(os.environ["YT_ACCOUNTS_DIR"]) / "alpha" / "request.token"
        self.assertTrue(legacy.is_symlink())
        self.assertTrue(target.is_file())
        self.assertEqual(target.read_text(encoding="utf-8"), '{"refresh_token": "legacy"}')
        r2 = A.migrate_legacy(target_name="alpha")
        self.assertFalse(r2["migrated"])
        self.assertEqual(r2["reason"], "already-migrated")


class MetaTest(Base):
    def acct(self, **kw):
        return A.Account(name="t", **kw)

    def test_tags_merge_dedupe_and_overlong(self):
        a = self.acct(tags_pool=["asmr", "relax"])
        meta = M.build_meta(
            a, title="T", tags=["relax", "sleep", "x" * 40], source_tags=["asmr", "rain"])
        self.assertEqual(meta["tags"], ["asmr", "relax", "rain", "sleep"])

    def test_tags_cap_count_and_chars(self):
        a = self.acct()
        many = ["tag%02d" % i for i in range(30)]
        meta = M.build_meta(a, title="T", tags=many)
        self.assertLessEqual(len(meta["tags"]), 15)

    def test_description_template(self):
        a = self.acct(description_template="{hook}\n{summary}\n{keywords}\ntags: {tags}")
        meta = M.build_meta(a, title="T", hook="H", summary="S",
                            keywords="k1 k2", tags=["a", "b"])
        self.assertEqual(meta["description"], "H\nS\nk1 k2\ntags: a, b")

    def test_description_template_missing_placeholder_is_empty(self):
        a = self.acct(description_template="hook={hook}|rest={nope}")
        meta = M.build_meta(a, title="T")
        self.assertEqual(meta["description"], "hook=|rest=")

    def test_explicit_description_wins(self):
        a = self.acct(description_template="tmpl")
        meta = M.build_meta(a, title="T", description="explicit")
        self.assertEqual(meta["description"], "explicit")

    def test_publish_at_z_and_force_private(self):
        a = self.acct(default_privacy="public")
        meta = M.build_meta(a, title="T", publish_at="2999-01-01T00:00:00Z")
        self.assertEqual(meta["privacyStatus"], "private")
        self.assertTrue(meta["publishAt"].endswith("Z"))
        self.assertTrue(any("private" in w for w in meta.warnings))

    def test_publish_at_past_and_naive_raise(self):
        a = self.acct()
        with self.assertRaises(M.MetaError):
            M.build_meta(a, title="T", publish_at="2000-01-01T00:00:00+00:00")
        with self.assertRaises(M.MetaError):
            M.build_meta(a, title="T", publish_at="2999-01-01T00:00:00")

    def test_title_required(self):
        with self.assertRaises(M.MetaError):
            M.build_meta(self.acct(), title="")

    def test_validate_meta_errors(self):
        bad = dict(title="x" * 101, description="y" * 5001, privacyStatus="ghost",
                   categoryId="99", playlistIds=["not-a-playlist-id!!"],
                   publishAt="2000-01-01T00:00:00+00:00")
        errs = M.validate_meta(bad)
        self.assertTrue(any("title" in e for e in errs))
        self.assertTrue(any("description" in e for e in errs))
        self.assertTrue(any("privacyStatus" in e for e in errs))
        self.assertTrue(any("categoryId" in e for e in errs))
        self.assertTrue(any("playlistId" in e for e in errs))
        self.assertTrue(any("publishAt" in e for e in errs))

    def test_validate_meta_category_id_accepts_int_and_numeric_string(self):
        for cid in (24, "24", " 7 "):
            errs = M.validate_meta(dict(title="T", categoryId=cid))
            self.assertFalse([e for e in errs if "categoryId" in e], (cid, errs))
        for cid in (0, 45, "abc", True):
            errs = M.validate_meta(dict(title="T", categoryId=cid))
            self.assertTrue([e for e in errs if "categoryId" in e], (cid, errs))

    def test_validate_go_meta_types_ok(self):
        good = dict(
            title="T", description="D", categoryId="24",
            privacyStatus="public", license="youtube", language="zh",
            tags=["a", "b"], playlistIds=["PL1234567890"], playlistTitles=["pl"],
            embeddable=True, publicStatsViewable=False, madeForKids=False,
            containsSyntheticMedia=True,
            publishAt="2999-01-01T00:00:00Z", recordingDate="2026-01-01T00:00:00Z",
        )
        self.assertEqual(M.validate_go_meta_types(good), [])

    def test_validate_go_meta_types_bad(self):
        bad = dict(categoryId=24, tags="a,b", playlistTitles="pl",
                   madeForKids="false", publishAt=1700000000)
        errs = M.validate_go_meta_types(bad)
        self.assertTrue(any("categoryId" in e for e in errs), errs)
        self.assertTrue(any("tags" in e for e in errs), errs)
        self.assertTrue(any("playlistTitles" in e for e in errs), errs)
        self.assertTrue(any("madeForKids" in e for e in errs), errs)
        self.assertTrue(any("publishAt" in e for e in errs), errs)

    def test_build_meta_category_id_is_str_after_json_roundtrip(self):
        meta = M.build_meta(self.acct(default_category=24), title="T")
        self.assertIsInstance(meta["categoryId"], str)
        self.assertEqual(meta["categoryId"], "24")
        loaded = json.loads(json.dumps(meta, ensure_ascii=False))
        self.assertIsInstance(loaded["categoryId"], str)
        self.assertEqual(loaded["categoryId"], "24")
        self.assertEqual(M.validate_go_meta_types(loaded), [])

    def test_build_meta_category_id_explicit_string(self):
        meta = M.build_meta(self.acct(), title="T", category_id="22")
        self.assertEqual(meta["categoryId"], "22")

    def test_build_meta_category_id_invalid_raises(self):
        for cid in ("abc", 99, 0, True, 1.5):
            with self.assertRaises(M.MetaError, msg=cid):
                M.build_meta(self.acct(), title="T", category_id=cid)

    def test_dump_meta_unicode(self):
        meta = M.build_meta(self.acct(), title="中文标题", tags=["asmr"])
        path = self.tmp / "m.json"
        M.dump_meta(meta, path)
        raw = path.read_text(encoding="utf-8")
        self.assertIn("中文标题", raw)
        self.assertEqual(json.loads(raw)["title"], "中文标题")


class LedgerTest(Base):
    def test_header_and_row_numbers(self):
        self.assertFalse(L.ledger_path().exists())
        n1 = L.append_row(dict(account="a", title="one"))
        n2 = L.append_row(dict(account="a", title="two"))
        self.assertEqual((n1, n2), (1, 2))
        header = L.ledger_path().read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(header, ",".join(L.HEADER))

    def test_csv_escaping(self):
        weird = 'a,b "q" \n newline'
        L.append_row(dict(account="a", title=weird))
        rows = list(L.iter_rows())
        self.assertEqual(rows[0]["title"], weird)

    def test_playlists_join_and_find(self):
        L.append_row(dict(account="a", video_id="dQw4w9WgXcQ",
                          source_url="https://src/x", playlists=["pl1", "pl2"]))
        rows = L.find(source_url="https://src/x")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["playlists"], "pl1;pl2")
        self.assertEqual(len(L.find(video_id="dQw4w9WgXcQ")), 1)
        self.assertEqual(len(L.find(video_id="nope0000000")), 0)

    def test_count_today_cross_account(self):
        L.append_row(dict(account="a", status="published"))
        L.append_row(dict(account="a", status="published"))
        L.append_row(dict(account="b", status="scheduled"))
        self.assertEqual(L.count_today("a"), 2)
        self.assertEqual(L.count_today("b"), 1)
        self.assertEqual(L.count_today("c"), 0)

    def test_count_today_excludes_failed_dry_run_and_empty(self):
        L.append_row(dict(account="a", status="published"))
        L.append_row(dict(account="a", status="failed"))
        L.append_row(dict(account="a", status="dry-run"))
        L.append_row(dict(account="a", status=""))
        self.assertEqual(L.count_today("a"), 1)
        self.assertEqual(L.count_today("a", include_failed=True), 2)

    def test_concurrent_appends_no_loss(self):
        results = []
        lock = threading.Lock()

        def worker(tag):
            local = []
            for i in range(25):
                local.append(L.append_row(dict(account=tag, title="t%d" % i)))
            with lock:
                results.extend(local)

        ts = [threading.Thread(target=worker, args=("a",)),
              threading.Thread(target=worker, args=("b",))]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        self.assertEqual(len(list(L.iter_rows())), 50)
        self.assertEqual(sorted(results), list(range(1, 51)))

    def test_summary(self):
        L.append_row(dict(account="a", status="published"))
        L.append_row(dict(account="b", status="failed"))
        s = L.summary(days=30)
        self.assertEqual(s["total"], 2)
        self.assertEqual(s["by_status"]["published"], 1)
        self.assertEqual(s["by_account"]["b"], 1)


class UploadE2ETest(Base):
    REQUIRED_KEYS = {
        "ok", "exit_code", "account", "channel", "video_id", "url", "privacy",
        "publish_at", "playlists", "tags_count", "thumbnail", "ledger_row",
        "warnings", "error", "duration",
    }

    def setUp(self):
        super().setUp()
        os.chmod(str(STUB), 0o755)
        self.acct_dir = self.write_account("acct1", daily_publish_cap=1, tags_pool=["asmr"])
        self.video = self.tmp / "clip.mp4"
        self.video.write_bytes(b"0" * 4096)

    def run_upload(self, *extra, env=None):
        cmd = [sys.executable, str(UPLOAD_PY), "--account", "acct1",
               "--file", str(self.video), "--json"] + list(extra)
        return subprocess.run(cmd, capture_output=True, text=True,
                              env=env if env is not None else self.sub_env())

    def run_upload_file(self, path, *extra, env=None):
        cmd = [sys.executable, str(UPLOAD_PY), "--account", "acct1",
               "--file", str(path), "--json"] + list(extra)
        return subprocess.run(cmd, capture_output=True, text=True,
                              env=env if env is not None else self.sub_env())

    def make_media(self, seconds=1.0):
        out = self.tmp / "real.mp4"
        cmd = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
               "-i", "testsrc=duration=%s:size=64x64:rate=5" % seconds,
               "-pix_fmt", "yuv420p", str(out)]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        return out

    def test_dry_run_no_upload_no_ledger(self):
        p = self.run_upload("--title", "Dry", "--dry-run")
        self.assertEqual(p.returncode, 0, p.stderr)
        obj = json.loads(p.stdout)
        self.assertTrue(obj["dry_run"])
        self.assertEqual(len(list(L.iter_rows())), 0)

    def test_real_run_parses_video_id_and_ledger(self):
        p = self.run_upload("--title", "Real")
        self.assertEqual(p.returncode, 0, p.stderr)
        obj = json.loads(p.stdout)
        self.assertTrue(obj["ok"])
        self.assertEqual(obj["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(obj["url"], "https://youtu.be/dQw4w9WgXcQ")
        self.assertEqual(obj["ledger_row"], 1)
        self.assertTrue(self.REQUIRED_KEYS.issubset(set(obj.keys())))
        rows = list(L.iter_rows())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["video_id"], "dQw4w9WgXcQ")
        self.assertEqual(rows[0]["status"], "published")
        # 成功发布 → 计入当日额度
        self.assertEqual(L.count_today("acct1"), 1)

    def test_failed_upload_records_failed_and_not_counted(self):
        env = self.sub_env()
        env["FAKE_YT_FAIL"] = "boom"
        p = self.run_upload("--title", "Boom", env=env)
        self.assertEqual(p.returncode, 5, p.stdout + p.stderr)
        rows = list(L.iter_rows())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "failed")
        # 失败行不占用日更额度
        self.assertEqual(L.count_today("acct1"), 0)

    def test_daily_cap_exit4_and_force(self):
        p1 = self.run_upload("--title", "One")
        self.assertEqual(p1.returncode, 0, p1.stderr)
        p2 = self.run_upload("--title", "Two")
        self.assertEqual(p2.returncode, 4, p2.stdout + p2.stderr)
        self.assertIn("上限", json.loads(p2.stdout)["error"])
        p3 = self.run_upload("--title", "Two", "--force")
        self.assertEqual(p3.returncode, 0, p3.stderr)
        self.assertEqual(len(list(L.iter_rows())), 2)

    def test_scheduled_status(self):
        p = self.run_upload("--title", "Later", "--publish-at", "2999-01-01T00:00:00Z")
        self.assertEqual(p.returncode, 0, p.stderr)
        rows = list(L.iter_rows())
        self.assertEqual(rows[0]["status"], "scheduled")

    def test_missing_title_exit2(self):
        # 已知账号 + 有文件，但缺 title → meta 校验失败 → exit 2
        cmd = [sys.executable, str(UPLOAD_PY), "--account", "acct1",
               "--file", str(self.video), "--json"]
        r = subprocess.run(cmd, capture_output=True, text=True, env=self.sub_env())
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_unknown_account_exit3(self):
        cmd = [sys.executable, str(UPLOAD_PY), "--account", "ghost",
               "--file", str(self.video), "--title", "T", "--json"]
        r = subprocess.run(cmd, capture_output=True, text=True, env=self.sub_env())
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)

    def test_missing_file_exit3(self):
        cmd = [sys.executable, str(UPLOAD_PY), "--account", "acct1",
               "--file", str(self.tmp / "nope.mp4"), "--title", "T", "--json"]
        r = subprocess.run(cmd, capture_output=True, text=True, env=self.sub_env())
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)

    def test_account_auto_no_accounts_exit3(self):
        os.environ["YT_ACCOUNTS_DIR"] = str(self.tmp / "empty")
        cmd = [sys.executable, str(UPLOAD_PY), "--account-auto",
               "--file", str(self.video), "--title", "T", "--json"]
        r = subprocess.run(cmd, capture_output=True, text=True, env=self.sub_env())
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)

    def test_duration_explicit_writes_ledger_and_receipt(self):
        p = self.run_upload("--title", "Dur", "--duration", "12.5")
        self.assertEqual(p.returncode, 0, p.stderr)
        obj = json.loads(p.stdout)
        self.assertAlmostEqual(float(obj["duration"]), 12.5, places=3)
        rows = list(L.iter_rows())
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["duration"]), 12.5, places=3)

    def test_duration_autoprobe_from_real_media(self):
        if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
            self.skipTest("ffmpeg/ffprobe 不可用")
        video = self.make_media(1.0)
        p = self.run_upload_file(video, "--title", "Auto")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        obj = json.loads(p.stdout)
        self.assertIsNotNone(obj["duration"])
        self.assertAlmostEqual(float(obj["duration"]), 1.0, delta=0.35)
        rows = list(L.iter_rows())
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["duration"]), 1.0, delta=0.35)

    def test_duration_non_media_warns_blank_and_still_uploads(self):
        fake = self.tmp / "fake_video.mp4"
        fake.write_bytes(b"this is definitely not a media file\n" * 64)
        p = self.run_upload_file(fake, "--title", "Junk")
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        obj = json.loads(p.stdout)
        self.assertTrue(obj["ok"])
        self.assertIsNone(obj["duration"])
        self.assertTrue(any("duration" in w for w in obj["warnings"]), obj["warnings"])
        rows = list(L.iter_rows())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["duration"], "")
        self.assertEqual(rows[0]["status"], "published")


if __name__ == "__main__":
    unittest.main(verbosity=2)
