#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/tests/test_ingest.py — youtube_ingest.py / lib/imaging.py 离线单元测试。

运行方式：
    cd <skill dir> && python3 -m unittest scripts.tests.test_ingest -v

依赖：系统 ffmpeg / ffprobe（用 lavfi 合成 1 秒测试素材）。全程离线，不联网、不上传。
所有临时文件仅写在 tempfile.TemporaryDirectory() 内。
"""
from __future__ import annotations

import importlib.util
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

try:  # 直接加载模块以单测 shorts_info（不跑 main）
    _spec = importlib.util.spec_from_file_location("youtube_ingest", INGEST)
    ingest = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(ingest)
except Exception:  # pragma: no cover
    ingest = None

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

    # ---------------- 竖屏/方形封面 + Shorts 判定（新增） ----------------

    def _make_video(self, size, duration=1):
        """用 lavfi 合成指定尺寸的黑帧视频（含音频），返回路径。"""
        path = self.dir / ("v_%s_%s.mp4" % (size.replace("x", "_"), duration))
        res = _ffmpeg([
            "-f", "lavfi", "-i", "color=c=black:s=%s:d=%s:r=1" % (size, duration),
            "-f", "lavfi", "-i", "sine=frequency=440:duration=%s" % duration,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-shortest", str(path),
        ])
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace")[-500:])
        return path

    def _cover_size(self, video):
        """对给定视频生成文字封面并返回其 (width, height)。"""
        cover = self.dir / ("cover_%s.jpg" % Path(video).stem)
        result = imaging.ensure_cover(str(video), str(cover), mode="raw", at_sec=0.0)
        self.assertTrue(Path(result).exists())
        streams = _probe_json(cover).get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        self.assertTrue(video_streams)
        return (video_streams[0].get("width"), video_streams[0].get("height"))

    def _make_test_pattern(self, size, duration=1):
        """用 lavfi testsrc2 合成指定尺寸的**非黑帧彩色**视频，返回路径。"""
        path = self.dir / ("p_%s.mp4" % size.replace("x", "_"))
        res = _ffmpeg([
            "-f", "lavfi", "-i", "testsrc2=s=%s:d=%s:r=10" % (size, duration),
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
        ])
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace")[-500:])
        return path

    def _image_size(self, image):
        """返回图片的 (width, height)。"""
        streams = _probe_json(image).get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        self.assertTrue(video_streams)
        return (video_streams[0].get("width"), video_streams[0].get("height"))

    def test_detect_canvas_unit(self):
        """detect_canvas 按宽高比返回竖屏/方形/横屏画布，非法参数回退横屏。"""
        self.assertEqual(imaging.detect_canvas(1920, 1080), (1080, 720))
        self.assertEqual(imaging.detect_canvas(1080, 1920), (1080, 1920))
        self.assertEqual(imaging.detect_canvas(1080, 1080), (1080, 1080))
        self.assertEqual(imaging.detect_canvas(None, None), (1080, 720))

    def test_portrait_text_cover_1080x1920(self):
        """竖屏黑帧视频 → 文字封面画布 1080x1920。"""
        video = self._make_video("320x568")
        self.assertEqual(self._cover_size(video), (1080, 1920))

    def test_square_text_cover_1080x1080(self):
        """方形黑帧视频 → 文字封面画布 1080x1080。"""
        video = self._make_video("320x320")
        self.assertEqual(self._cover_size(video), (1080, 1080))

    def test_horizontal_text_cover_1080x720(self):
        """横屏黑帧视频 → 文字封面画布 1080x720（防回归）。"""
        self.assertEqual(self._cover_size(self.video), (1080, 720))

    def test_portrait_source_landscape_canvas_uses_text_cover(self):
        """显式横屏画布 + 竖屏非黑帧源 → 比例不一致，改用文字封面 1080x720。"""
        video = self._make_test_pattern("360x640")
        cover = self.dir / "mismatch_cover.jpg"
        warnings = []
        result = imaging.ensure_cover(
            str(video), str(cover), mode="asmr", at_sec=0.0,
            size=(1080, 720), warnings=warnings,
        )
        self.assertTrue(Path(result).exists())
        self.assertGreater(Path(result).stat().st_size, 1024)
        self.assertEqual(self._image_size(cover), (1080, 720))
        self.assertTrue(
            any("比例不一致" in w for w in warnings),
            "warnings 应包含比例不一致提示: %r" % (warnings,),
        )

    def test_portrait_source_portrait_canvas_extracts_frame(self):
        """显式竖屏画布 + 竖屏非黑帧源 → 同向走抽帧，尺寸 1080x1920。"""
        video = self._make_test_pattern("360x640")
        cover = self.dir / "portrait_extract_cover.jpg"
        warnings = []
        result = imaging.ensure_cover(
            str(video), str(cover), mode="raw", at_sec=0.0,
            size=(1080, 1920), warnings=warnings,
        )
        self.assertTrue(Path(result).exists())
        self.assertEqual(self._image_size(cover), (1080, 1920))
        self.assertFalse(
            any("比例不一致" in w for w in warnings),
            "同向不应触发比例不一致提示: %r" % (warnings,),
        )

    def test_shorts_info_portrait_eligible(self):
        """竖屏 60s → eligible True，aspect 化简为 9:16。"""
        video = self._make_video("540x960", duration=60)
        info = ingest.shorts_info(str(video))
        self.assertTrue(info["eligible"])
        self.assertEqual(info["aspect"], "9:16")

    def test_shorts_info_landscape_ineligible(self):
        """横屏 1920x1080 → eligible False，reason 标注横屏。"""
        video = self._make_video("1920x1080", duration=1)
        info = ingest.shorts_info(str(video))
        self.assertFalse(info["eligible"])
        self.assertIn("横屏", info["reason"])

    def test_shorts_info_too_long_ineligible(self):
        """竖屏但时长 200s > 180s → eligible False，reason 含 180。"""
        video = self._make_video("540x960", duration=200)
        info = ingest.shorts_info(str(video))
        self.assertFalse(info["eligible"])
        self.assertIn("180", info["reason"])

    def test_shorts_info_audio_only(self):
        """纯音频 → eligible False 且 reason 含「纯音频」。"""
        info = ingest.shorts_info(str(self.audio))
        self.assertFalse(info["eligible"])
        self.assertIn("纯音频", info["reason"])

    def test_asset_json_contains_shorts(self):
        """真实 process_one 产出的 asset.json 必含 shorts 键且有 eligible。"""
        res = self._run(self.video, "--json")
        self.assertEqual(res.returncode, 0, res.stderr.decode("utf-8", "replace")[-500:])
        rec = json.loads(res.stdout.decode("utf-8"))
        asset_json = Path(rec["inbox_dir"]) / "asset.json"
        self.assertTrue(asset_json.exists())
        data = json.loads(asset_json.read_text(encoding="utf-8"))
        self.assertIn("shorts", data)
        self.assertIsNotNone(data["shorts"])
        self.assertIn("eligible", data["shorts"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
