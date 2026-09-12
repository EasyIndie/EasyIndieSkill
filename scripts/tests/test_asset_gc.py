#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/tests/test_asset_gc.py — asset_gc.py 离线单元测试。

全部临时目录均在 tempfile.TemporaryDirectory() 内，绝不触碰真实 HOME / ~/EasyIndie。
运行：
    cd <skill dir> && python3 -m unittest discover -s scripts/tests -t .
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GC = ROOT / "scripts" / "asset_gc.py"


def make_asset(work: Path, name: str, age_days: float, size: int = 2048,
               with_json: bool = True) -> Path:
    """在 work 下建一个 asset 目录，显式把目录 mtime 设为 age_days 天前。"""
    d = work / name
    d.mkdir(parents=True)
    if with_json:
        (d / "asset.json").write_text('{"asset_id": "%s"}' % name, encoding="utf-8")
    (d / "source.bin").write_bytes(b"x" * size)
    stamp = time.time() - age_days * 86400
    os.utime(d, (stamp, stamp))
    return d


class AssetGcTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.work = self.tmp / "work"
        self.work.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def run_gc(self, *args):
        env = dict(os.environ)
        env.pop("EASYINDIE_WORK", None)
        return subprocess.run(
            [sys.executable, str(GC), "--root", str(self.work), *args],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=env, text=True,
        )

    # 1. 到期删、未到期留
    def test_expired_deleted_fresh_kept(self):
        old = make_asset(self.work, "20200101-0000-old", age_days=40)
        fresh = make_asset(self.work, "20260912-1200-fresh", age_days=5)
        res = self.run_gc("--days", "30")
        self.assertEqual(res.returncode, 0)
        self.assertFalse(old.exists(), "到期 asset 应被删除")
        self.assertTrue(fresh.exists(), "未到期 asset 应保留")

    # 2. 目录名不匹配 pattern → 跳过
    def test_name_pattern_mismatch_skipped(self):
        bad = make_asset(self.work, "not-an-asset", age_days=400)
        bad2 = make_asset(self.work, "2020-0101-badshape", age_days=400)
        res = self.run_gc("--json")
        data = json.loads(res.stdout)
        self.assertEqual(data["deleted"], [])
        self.assertGreaterEqual(data["skipped_unsafe"], 2)
        self.assertTrue(bad.exists())
        self.assertTrue(bad2.exists())

    # 3. 目录名匹配但缺 asset.json → 跳过
    def test_missing_asset_json_skipped(self):
        nojson = make_asset(self.work, "20200101-0000-nojson",
                            age_days=400, with_json=False)
        res = self.run_gc("--json")
        data = json.loads(res.stdout)
        self.assertEqual(data["deleted"], [])
        self.assertEqual(data["skipped_unsafe"], 1)
        self.assertTrue(nojson.exists())

    # 4. --keep 白名单生效
    def test_keep_whitelist(self):
        pinned = make_asset(self.work, "20200101-0000-pinned", age_days=400)
        res = self.run_gc("--keep", "20200101-0000-pinned", "--json")
        data = json.loads(res.stdout)
        self.assertEqual(data["deleted"], [])
        self.assertIn("20200101-0000-pinned", data["kept_whitelist"])
        self.assertTrue(pinned.exists())

    # 5. --dry-run 不实际删除但报告准确
    def test_dry_run_reports_without_deleting(self):
        old = make_asset(self.work, "20200101-0000-old", age_days=40, size=4096)
        res = self.run_gc("--dry-run", "--json")
        data = json.loads(res.stdout)
        self.assertTrue(data["dry_run"])
        self.assertEqual(len(data["deleted"]), 1)
        self.assertEqual(data["deleted"][0]["name"], "20200101-0000-old")
        self.assertGreater(data["freed_bytes"], 0)
        self.assertTrue(old.exists(), "dry-run 不应实际删除")

    # 6. 无删除时 stdout 为空（cron 静默契约）
    def test_silent_when_nothing_to_do(self):
        make_asset(self.work, "20260912-1200-fresh", age_days=5)
        res = self.run_gc()
        self.assertEqual(res.returncode, 0)
        self.assertEqual(res.stdout, "", "无删除且磁盘充足时 stdout 必须为空")

    # 7. 磁盘压力模式：忽略年龄，删最旧者，输出非空
    def test_disk_pressure_ignores_age(self):
        fresh = make_asset(self.work, "20260912-1200-fresh", age_days=1)
        res = self.run_gc("--min-free-gb", "99999")
        self.assertEqual(res.returncode, 0)
        self.assertNotEqual(res.stdout, "", "压力模式必须输出")
        self.assertFalse(fresh.exists(), "压力模式应忽略 30 天限制删除最旧者")
        self.assertIn("磁盘压力模式", res.stdout)

    # 8. --json 结构字段可用
    def test_json_contract_fields(self):
        make_asset(self.work, "20200101-0000-old", age_days=40)
        make_asset(self.work, "not-an-asset", age_days=40)
        res = self.run_gc("--json")
        data = json.loads(res.stdout)
        for key in ("deleted", "freed_bytes", "skipped_unsafe", "free_gb"):
            self.assertIn(key, data)
        self.assertIsInstance(data["deleted"], list)
        self.assertIsInstance(data["freed_bytes"], int)
        self.assertIsInstance(data["skipped_unsafe"], int)
        self.assertIsInstance(data["free_gb"], float)

    # 额外：保护目录（inbox/ready/...）即使 --root 指过去也不删
    def test_protected_dirs_never_touched(self):
        for name in ("inbox", "ready", "published", "covers", "reports", "docs"):
            make_asset(self.work, name, age_days=400)
        res = self.run_gc("--json")
        data = json.loads(res.stdout)
        self.assertEqual(data["deleted"], [])
        for name in ("inbox", "ready", "published", "covers", "reports", "docs"):
            self.assertTrue((self.work / name).exists(), f"{name} 不应被删")

    # 额外：磁盘紧张但无可清理项 → 告警但 exit 0
    def test_pressure_no_candidates_warns_exit_zero(self):
        make_asset(self.work, "not-an-asset", age_days=400)
        res = self.run_gc("--min-free-gb", "99999")
        self.assertEqual(res.returncode, 0)
        self.assertIn("磁盘紧张", res.stdout)


if __name__ == "__main__":
    unittest.main()
