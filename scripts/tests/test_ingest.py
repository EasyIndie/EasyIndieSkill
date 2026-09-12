#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/tests/test_ingest.py — youtube_ingest.py / lib/imaging.py 离线单元测试。

运行方式：
    cd <skill dir> && python3 -m unittest scripts.tests.test_ingest -v

依赖：系统 ffmpeg / ffprobe（用 lavfi 合成 1 秒测试素材）。全程离线，不联网、不上传。
所有临时文件仅写在 tempfile.TemporaryDirectory() 内。
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INGEST = ROOT / "scripts" / "youtube_ingest.py"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))
try:
    import imaging
except ImportError:  # pragma: no cover
    imaging = None

HAVE_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
REQUIRED_FIELDS = [
    "ok", "asset_id", "inbox_dir", "source_path", "output_path", "mode",
    "duration", "size_mb", "cover", "probe", "warnings", "source_url", "source_title",
]


def _ffmpeg(args, timeout=180):
    return subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + args,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout,
    )


def _probe_json(path):
    res = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60,
    )
    return json.loads(res.stdout.decode("utf-8", "replace") or "{}")


@unittest.skipUnless(HAVE_FFMPEG and imaging is not None, "需要 ffmpeg/ffprobe 与 scripts/lib/imaging.py")
class IngestTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.out = self.dir / "inbox"
        self.video = self.dir / "sample.mp4"
        self.audio = self.dir / "sample.mp3"
        res = _ffmpeg([
            "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(self.video),
        ])
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace")[-500:])
        res = _ffmpeg([
            "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
            "-c:a", "libmp3lame", str(self.audio),
        ])
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace")[-500:])

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, media, *extra):
        cmd = [sys.executable, str(INGEST), "--in", str(media), "--out-dir", str(self.out)]
        cmd += list(extra)
        return subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=900,
        )

    def test_video_auto_raw(self):
        """有视频流素材 + auto → raw，输出 output.mp4 且 asset.json 字段齐全。"""
        res = self._run(self.video, "--json")
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace")[-500:])
        rec = json.loads(res.stdout.decode("utf-8"))
        self.assertEqual(rec["mode"], "raw")
        out = Path(rec["output_path"])
        self.assertEqual(out.name, "output.mp4")
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)
        for key in REQUIRED_FIELDS:
            self.assertIn(key, rec)
        asset_json = Path(rec["inbox_dir"]) / "asset.json"
        self.assertTrue(asset_json.exists())
        self.assertTrue(json.loads(asset_json.read_text(encoding="utf-8"))["ok"])
        self.assertTrue((Path(rec["inbox_dir"]) / "source.mp4").exists())

    def test_audio_auto(self):
        """纯音频素材 + auto → audio，输出 output.mp3。"""
        res = self._run(self.audio, "--json")
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace")[-500:])
        rec = json.loads(res.stdout.decode("utf-8"))
        self.assertEqual(rec["mode"], "audio")
        out = Path(rec["output_path"])
        self.assertEqual(out.name, "output.mp3")
        self.assertTrue(out.exists())
        self.assertGreater(out.stat().st_size, 0)

    def test_asmr_webm_has_video_and_audio(self):
        """--mode asmr → output.webm，且同时含视频流 + 音频流。"""
        res = self._run(self.video, "--mode", "asmr", "--json")
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace")[-800:])
        rec = json.loads(res.stdout.decode("utf-8"))
        out = Path(rec["output_path"])
        self.assertEqual(out.name, "output.webm")
        self.assertTrue(out.exists())
        streams = _probe_json(out).get("streams", [])
        codec_types = set(s.get("codec_type") for s in streams)
        self.assertIn("video", codec_types)
        self.assertIn("audio", codec_types)

    def test_black_frame_video_uses_text_cover(self):
        """黑帧视频 → ensure_cover 判定黑帧并生成 1080x720 文字封面。"""
        cover = self.dir / "cover.jpg"
        result = imaging.ensure_cover(str(self.video), str(cover), mode="raw", at_sec=0.0)
        self.assertTrue(Path(result).exists())
        self.assertGreater(Path(result).stat().st_size, 1024)
        streams = _probe_json(cover).get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        self.assertTrue(video_streams)
        self.assertEqual((video_streams[0].get("width"), video_streams[0].get("height")), (1080, 720))

    def test_dry_run_produces_no_output(self):
        """--dry-run 只探针，不产生 output 文件。"""
        res = self._run(self.video, "--dry-run", "--json")
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace")[-500:])
        rec = json.loads(res.stdout.decode("utf-8"))
        self.assertTrue(rec.get("dry_run"))
        asset_dir = Path(rec["inbox_dir"])
        found = list(asset_dir.glob("output.*")) if asset_dir.exists() else []
        self.assertEqual(found, [])

    def test_disk_full_exit_6(self):
        """磁盘不足（--min-free-mb 取极大值）→ 退出码 6。"""
        res = self._run(self.video, "--min-free-mb", "1000000000", "--json")
        self.assertEqual(res.returncode, 6, res.stderr.decode("utf-8", "replace")[-500:])


if __name__ == "__main__":
    unittest.main(verbosity=2)
