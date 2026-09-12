#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""youtube_upload.py — 多账号视频上传主入口（metaJSON 驱动）。

用法::

    python3 scripts/youtube_upload.py --account NAME --file PATH \
        [--title T] [--description D] [--tags a,b,c] [--source-tags a,b] \
        [--playlist 名字 ...] [--playlist-id ID ...] \
        [--privacy unlisted] [--publish-at ISO8601] [--category-id N] [--language zh] \
        [--thumbnail PATH] [--caption PATH] \
        [--mode asmr|raw|clip|audio] [--duration SECONDS] [--source-url URL] [--source-title S] \
        [--summary S] [--hook S] [--keywords S] \
        [--account-auto] [--force] [--dry-run] [--json] [--operator NAME]

退出码：0 成功 / 2 参数或校验错 / 3 账号或文件缺失 / 4 配额或风控上限 /
5 上传失败。``--dry-run`` 只生成 metaJSON 并打印将执行的命令，exit 0，不调用上传器。

上传器解析顺序：``$YT_UPLOADER`` > ``which youtubeuploader`` > ``~/go/bin/youtubeuploader``。
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
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import ytauto_accounts as A  # noqa: E402
from lib import ytauto_ledger as L  # noqa: E402
from lib import ytauto_meta as M  # noqa: E402

EXIT_OK = 0
EXIT_ARG = 2
EXIT_MISSING = 3
EXIT_QUOTA = 4
EXIT_UPLOAD = 5

_NETWORK_RE = re.compile(r"timeout|timed out|connection reset|\bEOF\b", re.I)
_FORBIDDEN_RE = re.compile(r"forbidden|unauthorized|\b403\b|\b401\b", re.I)
_QUOTA_RE = re.compile(r"quota", re.I)
_ID_PATTERNS = [
    re.compile(r"video ID[:\s]+([\w-]{11})"),
    re.compile(r"youtu\.be/([\w-]{11})"),
    re.compile(r'"id"\s*:\s*"([\w-]{11})"'),
]


def resolve_uploader() -> str:
    env = os.environ.get("YT_UPLOADER")
    if env:
        return env
    found = shutil.which("youtubeuploader")
    if found:
        return found
    return os.path.expanduser("~/go/bin/youtubeuploader")


def probe_duration(path: Path, timeout: float = 15.0) -> Optional[float]:
    """用 ffprobe 探测媒体时长（秒）。任何失败都返回 None（绝不抛错、绝不阻断上传）。"""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        val = float((proc.stdout or "").strip())
    except (TypeError, ValueError):
        return None
    if val <= 0:
        return None
    return val


def _fmt_duration(seconds: Optional[float]) -> str:
    """台账 duration 列：稳定可解析，保留 1 位小数；无值 → 空字符串。"""
    if seconds is None:
        return ""
    return "%.1f" % seconds


def classify_error(text: str) -> Tuple[str, str]:
    """把上传器输出归类为真因，返回 (kind, 人类可读说明)。"""
    t = text or ""
    low = t.lower()
    if _QUOTA_RE.search(t) and ("exceed" in low):
        return (
            "quotaExceeded",
            "API 配额已用尽（quotaExceeded）——YouTube Data API 每日配额在太平洋时间午夜重置，"
            "请次日再试或减少上传量。",
        )
    if _FORBIDDEN_RE.search(t):
        return (
            "forbidden",
            "权限/版权问题（forbidden|unauthorized）——检查 token scope、频道权限与素材版权。",
        )
    if _NETWORK_RE.search(t):
        return ("network", "网络类错误（timeout/connection reset/EOF）——已自动重试 1 次仍失败。")
    return ("unknown", t.strip()[:600] or "上传器未输出错误详情")


def _find_id_in_json(obj: Any) -> str:
    if isinstance(obj, dict):
        for k in ("id", "videoId", "video_id"):
            v = obj.get(k)
            if isinstance(v, str) and len(v) == 11:
                return v
        for v in obj.values():
            got = _find_id_in_json(v)
            if got:
                return got
    elif isinstance(obj, list):
        for v in obj:
            got = _find_id_in_json(v)
            if got:
                return got
    elif isinstance(obj, str):
        m = re.search(r"([\w-]{11})", obj)
        if m and obj == m.group(1):
            return obj
    return ""


def parse_video_id(out_path: Path, stdout: str, stderr: str) -> str:
    """优先 metaJSONout 文件里的 id，兜底 stdout/stderr 正则。"""
    if out_path.is_file():
        try:
            data = json.loads(out_path.read_text(encoding="utf-8"))
            vid = _find_id_in_json(data)
            if vid:
                return vid
        except (ValueError, OSError):
            pass
    for pat in _ID_PATTERNS:
        m = pat.search(stdout or "")
        if m:
            return m.group(1)
    for pat in _ID_PATTERNS:
        m = pat.search(stderr or "")
        if m:
            return m.group(1)
    return ""


def _split_csv(values: Optional[List[str]]) -> List[str]:
    out: List[str] = []
    for v in values or []:
        for part in str(v).split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def _flatten(values: Optional[List[List[str]]]) -> List[str]:
    out: List[str] = []
    for group in values or []:
        for v in group:
            out.append(v)
    return out


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="多账号视频上传（metaJSON 驱动）")
    p.add_argument("--account")
    p.add_argument("--account-auto", action="store_true", help="用 $YT_ACCOUNT 或默认账号")
    p.add_argument("--file")
    p.add_argument("--title")
    p.add_argument("--description")
    p.add_argument("--tags", action="append", help="逗号分隔，可重复")
    p.add_argument("--source-tags", action="append", help="逗号分隔，可重复")
    p.add_argument("--playlist", action="append", nargs="+", default=[], help="播放列表名")
    p.add_argument("--playlist-id", action="append", nargs="+", default=[], help="播放列表 ID")
    p.add_argument("--privacy")
    p.add_argument("--publish-at")
    p.add_argument("--category-id", type=int)
    p.add_argument("--language")
    p.add_argument("--thumbnail")
    p.add_argument("--caption")
    p.add_argument("--mode", choices=["asmr", "raw", "clip", "audio"])
    p.add_argument("--duration", type=float,
                   help="视频时长（秒），如 754.2；缺省时用 ffprobe 自动探测")
    p.add_argument("--source-url")
    p.add_argument("--source-title")
    p.add_argument("--summary")
    p.add_argument("--hook")
    p.add_argument("--keywords")
    p.add_argument("--force", action="store_true", help="跳过每日上限")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("--operator")
    return p


def _emit(receipt: Dict[str, Any], as_json: bool, lines: List[str]) -> None:
    if as_json:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    else:
        for line in lines:
            print(line)


def _die(receipt: Dict[str, Any], code: int, as_json: bool, msg: str) -> int:
    receipt["ok"] = False
    receipt["exit_code"] = code
    receipt["error"] = msg
    if as_json:
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
    else:
        print("❌ " + msg, file=sys.stderr)
    return code


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    receipt: Dict[str, Any] = dict(
        ok=False, exit_code=EXIT_ARG, account=None, channel=None, video_id="",
        url="", privacy=None, publish_at=None, playlists=[], tags_count=0,
        thumbnail=args.thumbnail, ledger_row=None, warnings=[], error="",
    )

    # 1. 账号解析
    if args.account:
        try:
            account = A.load_account(args.account)
        except A.AccountNotFound as e:
            return _die(receipt, EXIT_MISSING, args.as_json, str(e))
    elif args.account_auto:
        try:
            account = A.resolve_default()
        except A.AccountNotFound as e:
            return _die(receipt, EXIT_MISSING, args.as_json, str(e))
    else:
        return _die(receipt, EXIT_ARG, args.as_json,
                    "必须指定 --account NAME 或 --account-auto")

    receipt["account"] = account.name
    receipt["channel"] = account.channel_id or None

    # 2. 文件 / token / 凭据校验
    if not args.file:
        return _die(receipt, EXIT_ARG, args.as_json, "缺少 --file PATH")
    fpath = Path(os.path.expanduser(args.file))
    if not fpath.is_file() or fpath.stat().st_size == 0:
        return _die(receipt, EXIT_MISSING, args.as_json,
                    "文件不存在或为空: %s" % fpath)
    token_file = account.token_file
    secrets_file = account.secrets_file
    if not token_file.is_file():
        return _die(receipt, EXIT_MISSING, args.as_json,
                    "token 不存在: %s（期望路径）" % token_file)
    if not secrets_file.is_file():
        return _die(receipt, EXIT_MISSING, args.as_json,
                    "client secrets 不存在: %s（期望路径）" % secrets_file)
    if args.thumbnail and not Path(os.path.expanduser(args.thumbnail)).is_file():
        return _die(receipt, EXIT_MISSING, args.as_json,
                    "缩略图不存在: %s" % args.thumbnail)

    # 3. 风控：每日上限（dry-run 只做规划，不拦）
    used = L.count_today(account.name)
    if not args.force and not args.dry_run and used >= account.daily_publish_cap:
        return _die(
            receipt, EXIT_QUOTA, args.as_json,
            "今日已达上限 %d 条（已发 %d），--force 可强制" % (account.daily_publish_cap, used),
        )

    # 4. 构造 meta
    playlists = _flatten(args.playlist)
    playlist_ids = _flatten(args.playlist_id)
    try:
        meta = M.build_meta(
            account,
            title=args.title,
            description=args.description,
            tags=_split_csv(args.tags),
            source_tags=_split_csv(args.source_tags),
            playlists=playlists,
            playlist_ids=playlist_ids,
            privacy=args.privacy,
            publish_at=args.publish_at,
            category_id=args.category_id,
            language=args.language,
            thumbnail=args.thumbnail,
            caption=args.caption,
            summary=args.summary,
            hook=args.hook,
            keywords=args.keywords,
        )
    except (M.MetaError, ValueError) as e:
        return _die(receipt, EXIT_ARG, args.as_json, "meta 构造失败: %s" % e)

    warnings = list(meta.warnings)
    receipt["warnings"] = warnings
    receipt["privacy"] = meta.get("privacyStatus")
    receipt["publish_at"] = meta.get("publishAt")
    receipt["playlists"] = meta.get("playlistTitles", []) or []
    receipt["tags_count"] = len(meta.get("tags", []) or [])

    # 5. 时长：优先 --duration；否则 ffprobe 自动探测。探测失败只告警，不阻断上传。
    if args.duration is not None:
        duration_seconds: Optional[float] = float(args.duration)
    else:
        duration_seconds = probe_duration(fpath)
        if duration_seconds is None:
            warnings.append(
                "未能自动探测 duration（ffprobe 不可用 / 非媒体文件 / 超时），台账 duration 留空")
    receipt["duration"] = (
        round(duration_seconds, 3) if duration_seconds is not None else None)
    receipt["warnings"] = warnings

    # 写临时 metaJSON
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    tmpdir = A.youtube_dir() / "tmp"
    tmpdir.mkdir(parents=True, exist_ok=True)
    meta_path = tmpdir / ("%s-%s.json" % (account.name, stamp))
    out_path = tmpdir / ("%s-%s.out.json" % (account.name, stamp))
    M.dump_meta(meta, meta_path)

    uploader = resolve_uploader()
    cmd = [
        uploader, "-secrets", str(secrets_file), "-cache", str(token_file),
        "-filename", str(fpath), "-metaJSON", str(meta_path),
        "-metaJSONout", str(out_path),
    ]
    if args.thumbnail:
        cmd += ["-thumbnail", str(args.thumbnail)]
    if args.caption:
        cmd += ["-caption", str(args.caption)]

    # 12. dry-run
    if args.dry_run:
        size_mb = round(fpath.stat().st_size / 1048576.0, 2)
        est_row = dict(
            account=account.name, channel=account.channel_id, title=meta.get("title"),
            source_url=args.source_url or "", mode=args.mode or "",
            duration=_fmt_duration(duration_seconds), size_mb=size_mb,
            privacy=meta.get("privacyStatus"), publish_at=meta.get("publishAt") or "",
            playlists=";".join(meta.get("playlistTitles", []) or []),
            tags_count=len(meta.get("tags", []) or []), thumbnail=args.thumbnail or "",
            local_path=str(fpath), status="dry-run",
        )
        receipt.update(ok=True, exit_code=EXIT_OK, dry_run=True,
                       meta_path=str(meta_path), command=" ".join(cmd),
                       estimated_row=est_row)
        lines = [
            "🧪 dry-run（未上传）",
            "账号    : %s" % account.name,
            "metaJSON: %s" % meta_path,
            "命令    : %s" % " ".join(cmd),
            "预估台账: %s" % json.dumps(est_row, ensure_ascii=False),
        ]
        _emit(receipt, args.as_json, lines)
        return EXIT_OK

    # 6/11. 执行上传（网络错误自动重试 1 次）
    attempts = 0
    stdout = stderr = ""
    rc = 1
    while attempts < 2:
        attempts += 1
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
        except FileNotFoundError:
            return _die(receipt, EXIT_MISSING, args.as_json,
                        "上传器不存在: %s（设置 YT_UPLOADER 或安装 youtubeuploader）" % uploader)
        except OSError as e:
            return _die(receipt, EXIT_UPLOAD, args.as_json, "无法启动上传器: %s" % e)
        stdout, stderr = proc.stdout or "", proc.stderr or ""
        rc = proc.returncode
        if rc == 0:
            break
        combined = stdout + "\n" + stderr
        if attempts == 1 and _NETWORK_RE.search(combined):
            warnings.append("网络错误，自动重试 1 次")
            if out_path.exists():
                try:
                    out_path.unlink()
                except OSError:
                    pass
            continue
        break

    receipt["warnings"] = warnings
    combined = stdout + "\n" + stderr
    video_id = parse_video_id(out_path, stdout, stderr) if rc == 0 else ""
    receipt["video_id"] = video_id
    receipt["url"] = ("https://youtu.be/%s" % video_id) if video_id else ""

    if rc == 0 and not video_id:
        warnings.append("上传返回码 0，但未能解析 video_id（请检查 metaJSONout / stdout）")

    if rc == 0:
        status = "scheduled" if meta.get("publishAt") else "published"
        error = ""
    else:
        status = "failed"
        kind, human = classify_error(combined)
        error = "%s: %s" % (kind, human)

    size_mb = round(fpath.stat().st_size / 1048576.0, 2)
    row = dict(
        account=account.name,
        channel=account.channel_id,
        video_id=video_id,
        url=receipt["url"],
        title=meta.get("title"),
        source_url=args.source_url or "",
        source_title=args.source_title or "",
        mode=args.mode or "",
        duration=_fmt_duration(duration_seconds),
        size_mb=size_mb,
        privacy=meta.get("privacyStatus") or "",
        publish_at=meta.get("publishAt") or "",
        playlists=meta.get("playlistTitles", []) or [],
        tags_count=len(meta.get("tags", []) or []),
        thumbnail=args.thumbnail or "",
        local_path=str(fpath),
        cleanup="",
        status=status,
        note=error,
        operator=args.operator or "",
    )
    try:
        row_no = L.append_row(row)
    except OSError as e:
        warnings.append("台账写入失败: %s" % e)
        row_no = None
    receipt["ledger_row"] = row_no
    receipt["status"] = status

    if rc == 0:
        receipt.update(ok=True, exit_code=EXIT_OK, error="")
        lines = [
            "✅ 上传成功 [%s]" % status,
            "账号    : %s" % account.name,
            "video_id: %s" % (video_id or "(未解析)"),
            "URL     : %s" % (receipt["url"] or "-"),
            "隐私    : %s" % (meta.get("privacyStatus") or "-"),
            "台账行号: %s" % row_no,
        ] + ["⚠️ " + w for w in warnings]
        _emit(receipt, args.as_json, lines)
        return EXIT_OK

    receipt.update(ok=False, exit_code=EXIT_UPLOAD, error=error)
    lines = [
        "❌ 上传失败（exit=%s）" % rc,
        "账号    : %s" % account.name,
        "真因    : %s" % error,
        "台账行号: %s" % row_no,
    ] + ["⚠️ " + w for w in warnings]
    _emit(receipt, args.as_json, lines)
    return EXIT_UPLOAD


if __name__ == "__main__":
    sys.exit(main())
