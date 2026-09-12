#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/tests/test_feishu_fetch.py — feishu_fetch_attachment.py 离线单元测试。

运行方式：
    cd <skill dir> && python3 -m unittest scripts.tests.test_feishu_fetch -v

- 全部离线：通过环境变量 ``FEISHU_LARK_CLI`` 指向 ``scripts/tests/stubs/fake_lark_cli.sh``，
  脚本内部调用 lark-cli 时自然命中桩，不联网、不下载真实资源。
- 所有 out-dir / state / cwd 都位于 ``tempfile.TemporaryDirectory()`` 内。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "feishu_fetch_attachment.py"
STUB = ROOT / "scripts" / "tests" / "stubs" / "fake_lark_cli.sh"

CHAT_ID = "oc_test_xxx"
FILE_MID = "om_test_file_0001"
MEDIA_MID = "om_test_media_0002"
FILE_KEY = "file_v3_FAKE0001"
MEDIA_KEY = "file_v3_FAKE0002"
COVER_KEY = "img_v3_COVER02"


class FeishuFetchTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.out_dir = self.tmp / "out"
        self.state = self.tmp / "state.json"

    # ---------------------------------------------------------------- helpers
    def run_script(self, *extra, env=None, expect=None):
        cmd = [
            sys.executable, str(SCRIPT),
            "--chat-id", CHAT_ID,
            "--out-dir", str(self.out_dir),
            "--state", str(self.state),
        ] + list(extra)
        run_env = os.environ.copy()
        run_env["FEISHU_LARK_CLI"] = str(STUB)
        if env:
            run_env.update(env)
        proc = subprocess.run(
            cmd, cwd=str(self.tmp), env=run_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        if expect is not None:
            self.assertEqual(
                proc.returncode, expect,
                "exit=%d\nstdout=%s\nstderr=%s" % (proc.returncode, out, err),
            )
        return proc.returncode, out, err

    def run_json(self, *extra, env=None, expect=0):
        rc, out, err = self.run_script("--json", *extra, env=env, expect=expect)
        return json.loads(out)

    def run_no_out_dir(self, *extra, env=None, expect=0):
        """同 run_script，但不传 --out-dir，用于验证默认路径解析。"""
        cmd = [
            sys.executable, str(SCRIPT),
            "--chat-id", CHAT_ID,
            "--state", str(self.state),
        ] + list(extra)
        run_env = os.environ.copy()
        run_env["FEISHU_LARK_CLI"] = str(STUB)
        if env:
            run_env.update(env)
        proc = subprocess.run(
            cmd, cwd=str(self.tmp), env=run_env,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        self.assertEqual(
            proc.returncode, expect,
            "exit=%d\nstdout=%s\nstderr=%s" % (proc.returncode, out, err),
        )
        return proc.returncode, out, err

    def read_state(self):
        with open(self.state, "r", encoding="utf-8") as fh:
            return json.load(fh)

    # ---------------------------------------------------------------- tests
    def test_01_normal_fetch(self):
        doc = self.run_json("--minutes", "30")
        self.assertTrue(doc["ok"])
        self.assertEqual(doc["chat_id"], CHAT_ID)
        self.assertEqual(doc["window_minutes"], 30)
        self.assertEqual(doc["scanned"], 3)
        self.assertEqual(len(doc["found"]), 2)
        self.assertEqual(len(doc["downloaded"]), 2)
        self.assertEqual(len(doc["skipped"]), 0)
        self.assertEqual(len(doc["failed"]), 0)

        # 字段齐全
        for key in ("ok", "chat_id", "scanned", "window_minutes",
                    "found", "downloaded", "skipped", "failed"):
            self.assertIn(key, doc)
        for item in doc["downloaded"]:
            for key in ("message_id", "file_name", "path", "size_mb"):
                self.assertIn(key, item)
            self.assertTrue(Path(item["path"]).exists())
            self.assertGreater(Path(item["path"]).stat().st_size, 0)

        # 真实落盘文件
        names = {p.name for p in self.out_dir.iterdir()}
        self.assertIn("%s_Report-Final.pdf" % FILE_MID[-8:], names)
        self.assertIn("%s_clip.MOV" % MEDIA_MID[-8:], names)

        # 状态文件已写
        state = self.read_state()
        self.assertIn(FILE_MID, state)
        self.assertIn(MEDIA_MID, state)

    def test_02_idempotent(self):
        self.run_json("--minutes", "30")
        mtimes = {p.name: p.stat().st_mtime for p in self.out_dir.iterdir()}
        sizes = {p.name: p.stat().st_size for p in self.out_dir.iterdir()}

        doc = self.run_json("--minutes", "30")
        self.assertEqual(len(doc["downloaded"]), 0)
        self.assertEqual(len(doc["skipped"]), 2)
        self.assertEqual(len(doc["failed"]), 0)

        for p in self.out_dir.iterdir():
            self.assertEqual(p.stat().st_mtime, mtimes[p.name])
            self.assertEqual(p.stat().st_size, sizes[p.name])

    def test_03_force(self):
        self.run_json("--minutes", "30")
        doc = self.run_json("--minutes", "30", "--force")
        self.assertEqual(len(doc["downloaded"]), 2)
        self.assertEqual(len(doc["skipped"]), 0)

    def test_04_time_window(self):
        doc = self.run_json("--minutes", "1")
        self.assertEqual(doc["found"], [])
        self.assertEqual(len(doc["downloaded"]), 0)

        doc_all = self.run_json("--all")
        self.assertIsNone(doc_all["window_minutes"])
        self.assertEqual(len(doc_all["found"]), 2)

    def test_05_dry_run(self):
        doc = self.run_json("--minutes", "30", "--dry-run")
        self.assertTrue(doc.get("dry_run"))
        self.assertEqual(len(doc["found"]), 2)
        self.assertEqual(len(doc["would_download"]), 2)
        self.assertEqual(len(doc["downloaded"]), 0)
        self.assertFalse(self.state.exists())
        self.assertFalse(self.out_dir.exists() and any(self.out_dir.iterdir()))

    def test_06_with_cover(self):
        self.run_json("--minutes", "30", "--with-cover")
        cover = self.out_dir / ("%s_cover.jpg" % MEDIA_MID[-8:])
        self.assertTrue(cover.exists())
        self.assertGreater(cover.stat().st_size, 0)
        self.assertEqual(cover.read_text(), COVER_KEY)

    def test_07_download_failure(self):
        rc, out, err = self.run_script(
            "--json", "--minutes", "30",
            env={"FAKE_LARK_INJECT_FAIL": "1"}, expect=5,
        )
        doc = json.loads(out)
        self.assertFalse(doc["ok"])
        failed_ids = {f["message_id"] for f in doc["failed"]}
        self.assertIn(FILE_MID, failed_ids)
        # 其余条目仍然成功
        downloaded_ids = {d["message_id"] for d in doc["downloaded"]}
        self.assertIn(MEDIA_MID, downloaded_ids)
        self.assertTrue(
            (self.out_dir / ("%s_clip.MOV" % MEDIA_MID[-8:])).exists())

    def test_08_yaml_inbox_root(self):
        """未传 --out-dir 时，落盘根使用 feishu.yaml 的 inbox_root（支持 ~ 展开，拼 /YYYYMMDD）。

        用临时 HOME 隔离，绝不触碰真实 ~/.hermes/youtube/feishu.yaml。
        """
        fake_home = self.tmp / "home"
        yaml_dir = fake_home / ".hermes" / "youtube"
        yaml_dir.mkdir(parents=True)
        (yaml_dir / "feishu.yaml").write_text(
            "default_chat_id: %s\ninbox_root: ~/yaml-inbox\n" % CHAT_ID,
            encoding="utf-8",
        )
        rc, out, err = self.run_no_out_dir(
            "--minutes", "30", "--json",
            env={"HOME": str(fake_home)}, expect=0,
        )
        doc = json.loads(out)
        self.assertTrue(doc["ok"])
        self.assertEqual(len(doc["downloaded"]), 2)

        date = datetime.now().strftime("%Y%m%d")
        expected_root = fake_home / "yaml-inbox" / date
        for item in doc["downloaded"]:
            p = Path(item["path"])
            self.assertTrue(p.exists())
            self.assertEqual(p.parent, expected_root)
            self.assertTrue(str(p).startswith(str(fake_home / "yaml-inbox")))

        names = {p.name for p in expected_root.iterdir()}
        self.assertIn("%s_Report-Final.pdf" % FILE_MID[-8:], names)
        self.assertIn("%s_clip.MOV" % MEDIA_MID[-8:], names)


if __name__ == "__main__":
    unittest.main()
