#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/youtube_ingest.py — 入站素材处理器（飞书直传文件通道 / 本地文件）。

输入是「一个本地文件路径」或「一个目录」（目录内所有视频/音频按名排序逐个处理）。
典型来源：老板在飞书直接发视频/音频，Hermes 飞书适配器已把附件落盘为本地文件，
再把本地路径交给本脚本。本脚本只做本地落盘 / 探针 / 加工 / 封面，绝不调用任何上传接口。

产物（默认 <out-dir>=~/EasyIndie/work，可被 --out-dir / $EASYINDIE_WORK 覆盖；结构 <out-dir>/<asset_id>/）：
    source.<ext>   入站文件的一份副本（不动原缓存文件）
    output.*       加工结果（raw/clip→output.mp4, asmr→output.webm, audio→output.mp3）
    cover.jpg      封面（源抽帧或黑底文字封面）
    asset.json     素材档案（UTF-8）

加工实现方式说明（二选一，此处选「等价 ffmpeg 命令」）:
    本脚本直接调用与 scripts/processors/*.sh 等价的 ffmpeg 命令，而不是去 source 那些
    bash 处理器。原因：那些处理器围绕 URL 下载流程（download_video / download_audio_only）
    编写，输入是 URL；本通道输入已是本地文件，复刻其 ffmpeg 参数更直接、更可控。
    等价关系：
      raw    ≈ raw.sh   （原样：mp4 直接复制；非 mp4 remux -c copy，失败回退 H.264/AAC）
      asmr   ≈ asmr.sh  （1920x1080 黑帧 VP9 crf30，音频优先 -c:a copy，失败转 Opus）
      clip   ≈ clip.sh  （H.264 crf22 + AAC 128k，-ss/-to/-t 放在 -i 之前）
      audio  ≈ audio.sh （libmp3lame 192k）

退出码：0 成功 / 2 参数错 / 3 输入文件不存在 / 4 探针失败 / 5 加工失败 / 6 磁盘不足。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR / "lib"))
try:
    import imaging  # noqa: E402
except ImportError as _exc:  # pragma: no cover
    sys.stderr.write("缺少 scripts/lib/imaging.py: %s\n" % _exc)
    sys.exit(2)

EXIT_OK = 0
EXIT_ARGS = 2
EXIT_NOINPUT = 3
EXIT_PROBE = 4
EXIT_PROCESS = 5
EXIT_DISK = 6

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".flv", ".wmv", ".ts"}
AUDIO_EXT = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".aac", ".opus", ".wma"}
MEDIA_EXT = VIDEO_EXT | AUDIO_EXT

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")
DEFAULT_OUT = os.path.join(os.path.expanduser("~"), "EasyIndie", "work")
MODE_CHOICES = ("auto", "raw", "asmr", "clip", "audio")


class IngestError(Exception):
    """带退出码的处理器错误。"""

    def __init__(self, code, message):
        Exception.__init__(self, message)
        self.code = code
        self.message = message


def make_slug(name):
    """把任意名字净化为 slug：小写、非字母数字转 -、截断 40 字符。"""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    slug = slug[:40].strip("-")
    return slug or "asset"


def unique_dir(root, asset_id):
    """避免同分钟同 slug 冲突：追加 -2 / -3 …"""
    candidate = Path(root) / asset_id
    if not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = Path(root) / ("%s-%d" % (asset_id, index))
        if not candidate.exists():
            return candidate
        index += 1


def check_disk(path, min_free_mb):
    """可用空间不足时抛 IngestError(6)。返回可用 MB。"""
    try:
        st = os.statvfs(str(path))
    except OSError:
        st = os.statvfs(os.path.expanduser("~"))
    free_mb = (st.f_bavail * st.f_frsize) // (1024 * 1024)
    if free_mb < int(min_free_mb):
        raise IngestError(
            EXIT_DISK,
            "磁盘空间不足: 可用 %dMB < 需要 %dMB，请先清理（例如清理 %s 下的旧素材）"
            % (free_mb, int(min_free_mb), str(path)),
        )
    return free_mb


def _tail(raw, n=500):
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", "replace")
    else:
        text = str(raw)
    return text.strip()[-n:]


def run_cmd(cmd, timeout=1800):
    """执行外部命令，返回 CompletedProcess；执行层面的失败抛 IngestError(5)。"""
    try:
        return subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except subprocess.TimeoutExpired:
        raise IngestError(EXIT_PROCESS, "命令超时: %s" % " ".join(cmd))
    except OSError as exc:
        raise IngestError(EXIT_PROCESS, "无法执行 %s: %s" % (cmd[0], exc))


def probe_file(path):
    """ffprobe 探针，返回统一字典；失败抛 IngestError(4)。"""
    cmd = [
        FFPROBE, "-v", "error", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120
        )
    except subprocess.TimeoutExpired:
        raise IngestError(EXIT_PROBE, "ffprobe 超时: %s" % path)
    except OSError as exc:
        raise IngestError(EXIT_PROBE, "ffprobe 无法执行: %s" % exc)
    if res.returncode != 0:
        raise IngestError(
            EXIT_PROBE, "ffprobe 失败（文件损坏或非媒体）: %s" % _tail(res.stderr)
        )
    try:
        data = json.loads(res.stdout.decode("utf-8", "replace") or "{}")
    except ValueError:
        raise IngestError(EXIT_PROBE, "ffprobe 输出无法解析为 JSON")
    streams = data.get("streams") or []
    if not streams:
        raise IngestError(EXIT_PROBE, "文件中未发现任何流（可能是非媒体文件或已损坏）")
    fmt = data.get("format") or {}
    info = {
        "duration": 0.0,
        "size": 0,
        "bit_rate": None,
        "vcodec": None,
        "acodec": None,
        "sample_rate": None,
        "channels": None,
        "width": None,
        "height": None,
        "has_video": False,
        "has_audio": False,
    }
    for stream in streams:
        codec_type = stream.get("codec_type")
        if codec_type == "video":
            disposition = stream.get("disposition") or {}
            if disposition.get("attached_pic"):
                continue
            info["has_video"] = True
            info["vcodec"] = stream.get("codec_name") or info["vcodec"]
            info["width"] = stream.get("width") or info["width"]
            info["height"] = stream.get("height") or info["height"]
        elif codec_type == "audio":
            info["has_audio"] = True
            info["acodec"] = stream.get("codec_name") or info["acodec"]
            sample_rate = stream.get("sample_rate")
            if sample_rate and str(sample_rate).isdigit():
                info["sample_rate"] = int(sample_rate)
            info["channels"] = stream.get("channels") or info["channels"]
    if fmt.get("duration"):
        try:
            info["duration"] = round(float(fmt["duration"]), 2)
        except (TypeError, ValueError):
            pass
    if not info["duration"]:
        for stream in streams:
            stream_duration = stream.get("duration")
            if not stream_duration:
                continue
            try:
                info["duration"] = round(float(stream_duration), 2)
                break
            except (TypeError, ValueError):
                continue
    if fmt.get("size"):
        try:
            info["size"] = int(fmt["size"])
        except (TypeError, ValueError):
            pass
    if fmt.get("bit_rate"):
        try:
            info["bit_rate"] = int(fmt["bit_rate"])
        except (TypeError, ValueError):
            pass
    return info


def decide_mode(info, requested):
    """auto：有视频流 → raw；纯音频 → audio。显式指定则原样返回。"""
    if requested != "auto":
        return requested
    return "raw" if info["has_video"] else "audio"


# ---------------- 加工 ----------------

def proc_raw(src, asset_dir, info):
    out = asset_dir / "output.mp4"
    warnings = []
    if str(src).lower().endswith(".mp4"):
        shutil.copy2(str(src), str(out))
        return out, warnings
    res = run_cmd([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-map", "0:v?", "-map", "0:a?",
        "-c", "copy", "-movflags", "+faststart", str(out),
    ])
    if res.returncode == 0 and out.exists() and out.stat().st_size > 0:
        return out, warnings
    warnings.append("remux(-c copy) 失败，已回退 H.264/AAC 转码")
    res = run_cmd([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out),
    ])
    if res.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise IngestError(EXIT_PROCESS, "raw 加工失败: %s" % _tail(res.stderr))
    return out, warnings


def proc_asmr(src, asset_dir, info):
    out = asset_dir / "output.webm"
    if not info["has_audio"]:
        raise IngestError(EXIT_PROCESS, "asmr 模式需要音频流，但输入没有音频流")
    duration = int(info["duration"] or 0)
    black_duration = max(duration + 30, 60)
    base = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi",
        "-i", "color=c=black:s=1920x1080:d=%d:r=30" % black_duration,
        "-i", str(src), "-map", "1:a", "-map", "0:v",
        "-c:v", "libvpx-vp9", "-crf", "30", "-b:v", "0",
        "-deadline", "realtime", "-cpu-used", "5",
    ]
    res = run_cmd(base + ["-c:a", "copy", "-shortest", str(out)], timeout=3600)
    if res.returncode == 0 and out.exists() and out.stat().st_size > 0:
        return out, []
    res = run_cmd(
        base + ["-c:a", "libopus", "-b:a", "128k", "-shortest", str(out)],
        timeout=3600,
    )
    if res.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise IngestError(EXIT_PROCESS, "asmr 加工失败: %s" % _tail(res.stderr))
    return out, ["音频无法直接 copy，已转码为 Opus"]


def proc_clip(src, asset_dir, info, args):
    out = asset_dir / "output.mp4"
    opts = []
    if args.clip_start:
        opts += ["-ss", args.clip_start]
    if args.clip_end:
        opts += ["-to", args.clip_end]
    if args.clip_duration:
        opts += ["-t", args.clip_duration]
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
    ] + opts + [
        "-i", str(src), "-c:v", "libx264", "-crf", "22", "-preset", "fast",
        "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out),
    ]
    res = run_cmd(cmd)
    if res.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise IngestError(EXIT_PROCESS, "clip 加工失败: %s" % _tail(res.stderr))
    return out, []


def proc_audio(src, asset_dir, info):
    out = asset_dir / "output.mp3"
    res = run_cmd([
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(src), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", str(out),
    ])
    if res.returncode != 0 or not out.exists() or out.stat().st_size == 0:
        raise IngestError(EXIT_PROCESS, "audio 加工失败: %s" % _tail(res.stderr))
    return out, []


def _build_record(src, asset_dir, mode, info, args, dry_run):
    return {
        "ok": True,
        "asset_id": asset_dir.name,
        "inbox_dir": str(asset_dir),
        "source_path": str(src),
        "output_path": None,
        "mode": mode,
        "duration": info["duration"],
        "size_mb": 0.0,
        "cover": None,
        "probe": {
            "vcodec": info["vcodec"],
            "acodec": info["acodec"],
            "sample_rate": info["sample_rate"],
            "channels": info["channels"],
            "width": info["width"],
            "height": info["height"],
        },
        "warnings": [],
        "source_url": args.source_url or "",
        "source_title": args.source_title or "",
        "dry_run": bool(dry_run),
    }


def process_one(src, args, out_root):
    """处理单个素材，返回 asset 记录 dict。"""
    check_disk(out_root, args.min_free_mb)
    info = probe_file(src)
    mode = decide_mode(info, args.mode)
    slug = make_slug(args.name or Path(src).stem)
    asset_id = "%s-%s" % (datetime.now().strftime("%Y%m%d-%H%M"), slug)
    asset_dir = unique_dir(out_root, asset_id)
    record = _build_record(src, asset_dir, mode, info, args, args.dry_run)

    if args.dry_run:
        return record

    asset_dir.mkdir(parents=True, exist_ok=True)
    source_copy = asset_dir / ("source" + Path(src).suffix.lower())
    shutil.copy2(str(src), str(source_copy))
    record["source_path"] = str(source_copy)
    record["input_path"] = str(src)

    warnings = record["warnings"]
    if mode == "raw":
        out, extra = proc_raw(Path(src), asset_dir, info)
    elif mode == "asmr":
        out, extra = proc_asmr(Path(src), asset_dir, info)
    elif mode == "clip":
        out, extra = proc_clip(Path(src), asset_dir, info, args)
    else:
        out, extra = proc_audio(Path(src), asset_dir, info)
    warnings.extend(extra)
    record["output_path"] = str(out)
    record["size_mb"] = round(out.stat().st_size / (1024.0 * 1024.0), 2)

    # 封面
    cover_path = asset_dir / "cover.jpg"
    has_video = info["has_video"]
    if args.cover_frame is not None:
        at_sec = float(args.cover_frame)
    else:
        at_sec = min(3.0, max(0.0, (info["duration"] or 0.0) / 10.0))
    cover_source = str(src) if has_video else None
    cover_text = args.cover_text or args.source_title or slug
    try:
        result = imaging.ensure_cover(
            cover_source,
            str(cover_path),
            mode=mode,
            text=cover_text,
            at_sec=at_sec,
            force_text=bool(args.text_cover),
            warnings=warnings,
        )
        record["cover"] = str(result)
    except Exception as exc:  # 封面失败不阻断素材产出
        warnings.append("封面生成失败: %s" % exc)
        record["cover"] = None

    if has_video and not args.text_cover:
        try:
            if imaging.is_black_frame(str(src), at_sec=at_sec):
                warnings.append("源抽帧接近全黑，封面已改用文字封面")
        except Exception:
            pass

    asset_json = asset_dir / "asset.json"
    asset_json.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return record


def iter_inputs(path):
    """文件 → [path]；目录 → 目录内媒体文件（按名排序）；其它 → []。"""
    if path.is_file():
        return [path]
    if path.is_dir():
        return [
            p for p in sorted(path.iterdir(), key=lambda p: p.name.lower())
            if p.is_file() and p.suffix.lower() in MEDIA_EXT
        ]
    return []


def human_summary(record):
    if not record.get("ok"):
        return "❌ 失败: %s (%s)" % (record.get("source_path"), record.get("error"))
    if record.get("dry_run"):
        return "ℹ️ [dry-run] %s ｜ 模式=%s ｜ 时长=%ss" % (
            record["asset_id"], record["mode"], record["duration"],
        )
    return (
        "✅ %s\n   模式: %s ｜ 时长: %ss ｜ 输出: %sMB\n   输出: %s\n   封面: %s"
        % (
            record["asset_id"], record["mode"], record["duration"],
            record["size_mb"], record["output_path"], record["cover"],
        )
    )


def build_parser():
    parser = argparse.ArgumentParser(
        prog="youtube_ingest.py",
        description="入站素材处理器（飞书直传文件通道）：落盘/探针/加工/封面，不执行上传。",
    )
    parser.add_argument("--in", dest="in_path", required=True,
                        help="入站文件路径，或包含媒体文件的目录")
    parser.add_argument("--mode", choices=MODE_CHOICES, default="auto",
                        help="加工模式（默认 auto：有视频流→raw，纯音频→audio）")
    parser.add_argument("--out-dir", dest="out_dir", default=None,
                        help="素材根目录（默认 $EASYINDIE_WORK 或 ~/EasyIndie/work）")
    parser.add_argument("--name", default=None, help="覆盖 asset slug（净化后使用）")
    parser.add_argument("--clip-start", dest="clip_start", default=None, help="截取起点 HH:MM:SS")
    parser.add_argument("--clip-end", dest="clip_end", default=None, help="截取终点 HH:MM:SS")
    parser.add_argument("--clip-duration", dest="clip_duration", default=None, help="截取时长（秒）")
    parser.add_argument("--source-url", dest="source_url", default="", help="源链接（可选，写入档案）")
    parser.add_argument("--source-title", dest="source_title", default="", help="源标题（可选，写入档案/封面文字）")
    parser.add_argument("--cover-frame", dest="cover_frame", type=float, default=None,
                        help="抽帧时间秒（默认 min(3, duration/10)）")
    parser.add_argument("--text-cover", dest="text_cover", action="store_true",
                        help="强制使用文字封面")
    parser.add_argument("--cover-text", dest="cover_text", default=None,
                        help="文字封面文字（默认用源标题/slug）")
    parser.add_argument("--min-free-mb", dest="min_free_mb", type=int, default=500,
                        help="处理前要求的最小可用空间 MB（默认 500）")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true",
                        help="只探针不加工")
    parser.add_argument("--json", dest="as_json", action="store_true",
                        help="以 JSON 输出档案（目录输入时为数组）")
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    src = Path(os.path.expanduser(args.in_path))
    if not src.exists():
        sys.stderr.write("输入不存在: %s\n" % src)
        return EXIT_NOINPUT
    # 优先级：CLI --out-dir > $EASYINDIE_WORK > 默认 ~/EasyIndie/work
    out_root = Path(os.path.expanduser(
        args.out_dir or os.environ.get("EASYINDIE_WORK") or DEFAULT_OUT
    ))
    inputs = iter_inputs(src)
    if not inputs:
        sys.stderr.write("输入中没有可处理的媒体文件: %s\n" % src)
        return EXIT_NOINPUT

    try:
        out_root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        sys.stderr.write("无法创建输出目录 %s: %s\n" % (out_root, exc))
        return EXIT_ARGS

    results = []
    error_codes = []
    single = len(inputs) == 1
    for item in inputs:
        try:
            results.append(process_one(item, args, out_root))
        except IngestError as exc:
            if single:
                sys.stderr.write("%s\n" % exc.message)
                return exc.code
            results.append({"ok": False, "source_path": str(item), "error": exc.message})
            error_codes.append(exc.code)

    if args.as_json:
        payload = results[0] if single else results
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        for record in results:
            sys.stdout.write(human_summary(record) + "\n")

    if error_codes:
        return error_codes[0]
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
