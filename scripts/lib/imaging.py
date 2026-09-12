#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scripts/lib/imaging.py — 封面生成（源抽帧 / 黑底文字封面）。

运行环境: macOS 系统 python3 (3.9)。

重要前提（已实测）: 本机 ffmpeg 8.1.1 构建**不含 freetype/libass** ——
`ffmpeg -filters` 里没有 `drawtext`、没有 `subtitles`/`ass`。
因此**文字封面不使用 drawtext**，全部改用 Pillow 绘制；drawtext 代码路径已移除。

文字封面（text_cover）:
  - Pillow 可用: 纯黑底 + 居中白字，默认 1080x720，输出 JPEG(quality≈92)；
    换行按**像素宽度**(``draw.textlength``)测量，最多 3 行、超出加省略号；
    行距 = 字号 x 1.35；字号自适应 64 -> 48 -> 40（以 720 高度为基准等比缩放）；
    字体以 ``ImageFont.truetype(path, size, index=0)`` 加载（.ttc 需要 index），
    回退顺序见 FONT_CANDIDATES，全部缺失则抛明确错误（含尝试过的路径）。
  - Pillow 不可用: 退化为**纯黑 JPEG**（用 ffmpeg 的 color 源生成，无需 freetype），
    并通过 warnings 回传「Pillow 不可用，已退化为纯黑封面」，整体不失败。

黑帧判定（is_black_frame）:
  - 首选 **Pillow 像素统计**: 抽帧 -> 转灰度 -> 亮度最大值 <= BLACK_LUMA_MAX
    或标准差 <= BLACK_STDDEV_MAX 即判为黑帧；
  - Pillow 不可用时回退 ffmpeg ``blackframe`` 滤镜解析 ``pblack``（若该滤镜存在）。

所有 ffmpeg 调用均通过 subprocess.run(..., timeout=...) 执行，失败信息包含 stderr 尾部。
"""
from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

# 字体候选：必须支持中文，缺失则依次回退，全部缺失则抛错。
FONT_CANDIDATES = [
    "/System/Library/Fonts/PingFang.ttc",
    "/System/Library/Fonts/Supplemental/Songti.ttc",
    "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    "/Library/Fonts/Arial.ttf",
]
PLACEHOLDER = "无题素材"
MAX_LINES = 3
LINE_SPACING_RATIO = 1.35
# 以 720 高度为基准的字号比例：64 -> 48 -> 40
FONT_SIZE_RATIOS = (64.0 / 720.0, 48.0 / 720.0, 40.0 / 720.0)
TEXT_WIDTH_RATIO = 0.86
JPEG_QUALITY = 92

# 黑帧判定阈值（Pillow 像素统计）
BLACK_LUMA_MAX = 16
BLACK_STDDEV_MAX = 2.0
# ffmpeg blackframe 回退路径阈值
BLACK_AMOUNT = 95
BLACK_THRESHOLD = 32
BLACK_PBLACK = 90

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")

try:  # Pillow 为可选依赖：可用则用于文字封面与黑帧判定
    from PIL import Image, ImageDraw, ImageFont, ImageStat  # noqa: F401
    _HAS_PIL = True
except ImportError:  # pragma: no cover - 依赖环境
    _HAS_PIL = False


def _tail(raw, n=500):
    """把 stderr 字节串解码并截取尾部，用于错误信息。"""
    if raw is None:
        return ""
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", "replace")
    else:
        text = str(raw)
    return text.strip()[-n:]


def _note(warnings, message):
    """把提示写入可选的 warnings 列表（不破坏旧调用）。"""
    if warnings is not None:
        warnings.append(message)


def _font_candidates():
    """返回按优先级排列的字体候选路径列表（含 EASYINDIE_FONT 覆盖）。"""
    candidates = []
    env = os.environ.get("EASYINDIE_FONT")
    if env:
        candidates.append(env)
    candidates.extend(FONT_CANDIDATES)
    return candidates


def _load_font(size):
    """加载指定字号的中文字体（.ttc 取 index=0）；全部失败抛 RuntimeError。"""
    tried = []
    last_error = None
    for path in _font_candidates():
        if not os.path.exists(path):
            tried.append("%s(不存在)" % path)
            continue
        try:
            return ImageFont.truetype(path, size, index=0)
        except Exception as exc:  # noqa: BLE001 - 逐个回退
            last_error = exc
            tried.append("%s(%s)" % (path, exc))
    raise RuntimeError(
        "无法加载支持中文的字体，尝试过: %s；最后错误: %s"
        % ("、".join(tried), last_error)
    )


def _wrap_pixels(draw, text, font, max_width):
    """按像素宽度自动换行（保留显式换行）。返回行列表，可能超过 MAX_LINES。"""
    lines = []
    for para in str(text).split("\n"):
        current = ""
        for ch in para:
            trial = current + ch
            if current and draw.textlength(trial, font=font) > max_width:
                lines.append(current)
                current = ch
            else:
                current = trial
        lines.append(current)
    return lines or [PLACEHOLDER]


def _truncate_lines(draw, lines, font, max_width):
    """截断到 MAX_LINES 行，末行按像素宽度裁剪后追加省略号。"""
    kept = lines[:MAX_LINES]
    last = kept[-1]
    while last and draw.textlength(last + "…", font=font) > max_width:
        last = last[:-1]
    kept[-1] = last + "…"
    return kept


def _choose_font_and_lines(draw, message, width, height):
    """自适应字号（64->48->40），返回 (font, lines, fontsize)。"""
    max_width = width * TEXT_WIDTH_RATIO
    sizes = [max(12, int(round(height * ratio))) for ratio in FONT_SIZE_RATIOS]
    font = None
    lines = None
    for size in sizes:
        candidate = _load_font(size)
        candidate_lines = _wrap_pixels(draw, message, candidate, max_width)
        if len(candidate_lines) <= MAX_LINES:
            font, lines, chosen = candidate, candidate_lines, size
            break
    if font is None:
        chosen = sizes[-1]
        font = _load_font(chosen)
        lines = _truncate_lines(
            draw, _wrap_pixels(draw, message, font, max_width), font, max_width
        )
    return font, lines, chosen


def _write_black_jpeg(out_path, width, height):
    """Pillow 不可用时的兜底：用 ffmpeg color 源生成纯黑 JPEG（无需 freetype）。"""
    out_path = Path(out_path)
    cmd = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=black:s=%dx%d:d=1" % (width, height),
        "-frames:v", "1", "-q:v", "2", str(out_path),
    ]
    res = None
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError("生成纯黑封面失败（Pillow 与 ffmpeg 均不可用）: %s" % exc)
    if res.returncode != 0 or not out_path.exists() or out_path.stat().st_size == 0:
        raise RuntimeError("生成纯黑封面失败: %s" % _tail(res.stderr))
    return out_path


def _orientation(width, height):
    """按宽高比返回方向：'portrait' / 'square' / 'landscape'；参数非法返回 None。"""
    try:
        w = float(width)
        h = float(height)
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    ratio = w / h
    if ratio < 0.98:
        return "portrait"
    if ratio <= 1.02:
        return "square"
    return "landscape"


def detect_canvas(width, height):
    """按源宽高比返回封面画布尺寸 (w, h)。

    竖屏（width/height < 0.98）→ (1080, 1920)
    方形（0.98 <= ratio <= 1.02）→ (1080, 1080)
    横屏（ratio > 1.02）→ (1080, 720)   # 现状，保持不变
    参数非法/None → (1080, 720)
    """
    try:
        w = float(width)
        h = float(height)
    except (TypeError, ValueError):
        return (1080, 720)
    if w <= 0 or h <= 0:
        return (1080, 720)
    ratio = w / h
    if ratio < 0.98:
        return (1080, 1920)
    if ratio <= 1.02:
        return (1080, 1080)
    return (1080, 720)


def probe_size(path):
    """用 ffprobe 取第一个视频流的 (width, height)；无视频流/失败返回 None。"""
    cmd = [
        FFPROBE, "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height", "-of", "csv=p=0", str(path),
    ]
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    text = (res.stdout or b"").decode("utf-8", "replace").strip()
    if not text:
        return None
    first = text.splitlines()[0]
    parts = [p for p in first.split(",") if p != ""]
    if len(parts) < 2:
        return None
    try:
        width = int(parts[0])
        height = int(parts[1])
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    return (width, height)


def _run_extract(cmd, out_path):
    """执行抽帧命令并校验产物，失败返回 False。"""
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if res.returncode != 0:
        return False
    return out_path.exists() and out_path.stat().st_size > 0


def extract_frame(video, out_path, at_sec, scale_width=None):
    """在 at_sec 秒处抽取一帧到 out_path。成功返回 True，失败返回 False。

    scale_width=None → 行为与旧版完全一致（不加 -vf）。
    scale_width=1080 → 先尝试 ``-vf scale=1080:-2``（宽度规范到 1080、高度按
    比例且取偶数）；缩放抽帧失败时**回退**到不缩放的原始抽帧，不阻断封面生成。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        at = max(0.0, float(at_sec))
    except (TypeError, ValueError):
        at = 0.0
    base = [
        FFMPEG, "-y", "-hide_banner", "-loglevel", "error",
        "-ss", repr(at), "-i", str(video),
    ]
    if scale_width:
        try:
            width = max(2, int(scale_width))
        except (TypeError, ValueError):
            width = None
        if width:
            scaled = base + [
                "-vf", "scale=%d:-2" % width,
                "-frames:v", "1", "-q:v", "2", str(out_path),
            ]
            if _run_extract(scaled, out_path):
                return True
    cmd = base + ["-frames:v", "1", "-q:v", "2", str(out_path)]
    return _run_extract(cmd, out_path)


def _pil_is_black(path):
    """用 Pillow 像素统计判断图片是否接近全黑（失败返回 False）。"""
    if not _HAS_PIL:
        return False
    try:
        with Image.open(str(path)) as image:
            gray = image.convert("L")
            extrema = gray.getextrema()
            stat = ImageStat.Stat(gray)
            stddev = stat.stddev[0] if stat.stddev else 0.0
    except Exception:  # noqa: BLE001 - 任何读取失败都保守判为非黑
        return False
    if extrema[1] <= BLACK_LUMA_MAX:
        return True
    return stddev <= BLACK_STDDEV_MAX


def _blackframe_ffmpeg(path, at_sec, timeout):
    """回退方案：用 ffmpeg blackframe 滤镜解析 pblack（滤镜不存在则返回 False）。"""
    cmd = [FFMPEG, "-hide_banner", "-loglevel", "info"]
    if at_sec is not None:
        try:
            cmd += ["-ss", repr(max(0.0, float(at_sec)))]
        except (TypeError, ValueError):
            pass
    cmd += [
        "-i", str(path), "-frames:v", "1",
        "-vf", "blackframe=amount=%d:threshold=%d" % (BLACK_AMOUNT, BLACK_THRESHOLD),
        "-f", "null", "-",
    ]
    try:
        res = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    values = re.findall(r"pblack:(\d+)", res.stderr.decode("utf-8", "replace"))
    if not values:
        return False
    try:
        return max(int(v) for v in values) >= BLACK_PBLACK
    except ValueError:
        return False


def is_black_frame(path, at_sec=None, timeout=60):
    """判断给定视频/图片（可选 at_sec 处的一帧）是否接近全黑。

    首选 Pillow 像素统计（图片直接分析；视频先抽帧再分析）；
    Pillow 不可用时回退 ffmpeg ``blackframe``。无法判定时返回 False（保守）。
    """
    p = Path(path)
    if not p.exists():
        return False
    if _HAS_PIL:
        if p.suffix.lower() in IMAGE_EXT:
            return _pil_is_black(p)
        handle, tmp_path = tempfile.mkstemp(suffix=".jpg")
        os.close(handle)
        try:
            at = 0.0 if at_sec is None else at_sec
            if extract_frame(str(p), tmp_path, at):
                return _pil_is_black(tmp_path)
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    return _blackframe_ffmpeg(str(path), at_sec, timeout)


def text_cover(out_path, text=None, *, width=1080, height=720, title=None, warnings=None):
    """生成黑底白字封面（居中，最多 3 行，按像素宽度自动换行）。

    使用 Pillow 绘制（本机 ffmpeg 无 freetype，drawtext 不可用）。
    Pillow 缺失时退化为纯黑 JPEG 并通过 warnings 回传；找不到中文字体时抛错。
    返回写入的 Path。warnings 为可选的 list，用于回传非致命提示。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    message = str(text or title or PLACEHOLDER).strip() or PLACEHOLDER

    if not _HAS_PIL:
        _note(warnings, "Pillow 不可用，已退化为纯黑封面")
        return _write_black_jpeg(out_path, width, height)

    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    font, lines, fontsize = _choose_font_and_lines(draw, message, width, height)

    line_height = fontsize * LINE_SPACING_RATIO
    y = (height - line_height * len(lines)) / 2.0
    for line in lines:
        try:
            line_width = draw.textlength(line, font=font)
        except Exception:  # noqa: BLE001 - 测量失败则按居中近似
            line_width = 0
        draw.text(
            ((width - line_width) / 2.0, y), line, font=font, fill=(255, 255, 255)
        )
        y += line_height
    image.save(str(out_path), "JPEG", quality=JPEG_QUALITY)
    return out_path


def ensure_cover(
    source_video_or_none,
    out_path,
    *,
    mode="raw",
    text=None,
    at_sec=None,
    force_text=False,
    warnings=None,
    size=None
):
    """确保生成封面：优先源抽帧（黑帧则改文字），否则文字封面。

    - force_text 或没有源视频 → 直接文字封面；
    - 抽帧成功但该帧接近全黑（黑帧视频，如 ASMR 黑屏源）→ 文字封面；
    - 抽帧失败（超时长/无视频流/ffmpeg 报错）→ 文字封面。
    返回封面 Path。mode 仅用于日志语境，不改变判定逻辑。

    size=(w, h) 显式给出封面画布；未给出时自动推导：能 probe_size 到源尺寸
    则 detect_canvas(width, height)，否则（纯音频/无源/探测失败）用 (1080, 720)。
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    src = None
    if source_video_or_none and os.path.exists(str(source_video_or_none)):
        src = str(source_video_or_none)

    probed = probe_size(src) if src else None
    if size is not None:
        canvas = (int(size[0]), int(size[1]))
    elif probed:
        canvas = detect_canvas(probed[0], probed[1])
    else:
        canvas = (1080, 720)
    width, height = canvas

    if force_text or not src:
        return text_cover(
            out_path, text=text, width=width, height=height, warnings=warnings
        )

    # 抽帧比例错配保护：源比例与画布比例不同向（如 asmr 源竖屏、画布横屏）时，
    # 跨比例无法在不裁切/不加黑边的前提下转换，直接用画布尺寸的文字封面兜底。
    if probed is not None:
        src_orientation = _orientation(probed[0], probed[1])
        canvas_orientation = _orientation(width, height)
        if (
            src_orientation is not None
            and canvas_orientation is not None
            and src_orientation != canvas_orientation
        ):
            _note(warnings, "源比例与产物比例不一致，封面已改用文字封面")
            return text_cover(
                out_path, text=text, width=width, height=height, warnings=warnings
            )

    # 竖屏/方形画布规范到 1080 宽（横屏画布不缩放，保持现状）。
    scale_width = None
    if canvas != (1080, 720) and (probed is None or probed[0] != 1080):
        scale_width = 1080

    at = 0.0 if at_sec is None else float(at_sec)
    if extract_frame(src, out_path, at, scale_width=scale_width):
        if is_black_frame(str(out_path)):
            return text_cover(
                out_path, text=text, width=width, height=height, warnings=warnings
            )
        return out_path
    return text_cover(
        out_path, text=text, width=width, height=height, warnings=warnings
    )
