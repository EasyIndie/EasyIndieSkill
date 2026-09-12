#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ytauto_ledger.py — 上传台账 CSV（追加写 + 文件锁，标准库实现）。

路径：``$YT_LEDGER``，默认 ``$YOUTUBE_DIR/ledger.csv``（``~/.hermes/youtube/ledger.csv``）。
表头顺序固定，见 ``HEADER``。

并发：写操作使用 ``fcntl.flock`` 文件锁 + 进程内 ``threading.Lock``（双保险），
追加写不丢行。CSV 转义交给标准库 ``csv`` 模块（逗号/换行/引号均安全）。
"""

from __future__ import annotations

import csv
import fcntl
import io
import os
import threading
from datetime import date as _date
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

__all__ = [
    "HEADER",
    "ledger_path",
    "ensure_ledger",
    "append_row",
    "iter_rows",
    "find",
    "count_today",
    "summary",
]

HEADER: List[str] = [
    "ts", "account", "channel", "video_id", "url", "title", "source_url",
    "source_title", "mode", "duration", "size_mb", "privacy", "publish_at",
    "playlists", "tags_count", "thumbnail", "local_path", "cleanup", "status",
    "note", "operator",
]

_THREAD_LOCK = threading.Lock()

# 计入日更额度的状态：只有真实发布（已发布 / 已排程）。
# failed / dry-run / 空 status 不占用额度。
COUNTED_STATUSES = ("published", "scheduled")


def ledger_path() -> Path:
    override = os.environ.get("YT_LEDGER")
    if override:
        return Path(os.path.expanduser(override))
    from . import ytauto_accounts as _acc
    return _acc.youtube_dir() / "ledger.csv"


def _now_iso() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return ";".join(str(x) for x in v)
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def ensure_ledger() -> Path:
    """确保台账文件存在且带表头；返回路径。"""
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() or path.stat().st_size == 0:
        with _THREAD_LOCK:
            with open(path, "a+", newline="", encoding="utf-8") as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    f.seek(0)
                    if not f.read().strip():
                        csv.writer(f).writerow(HEADER)
                        f.flush()
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return path


def _count_data_rows(text: str) -> int:
    if not text.strip():
        return 0
    rows = [r for r in csv.reader(io.StringIO(text)) if any(c.strip() for c in r)]
    return max(0, len(rows) - 1)


def append_row(row: Dict[str, Any]) -> int:
    """追加一行，返回该行的数据行号（1-based，不含表头）。"""
    path = ledger_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    row = dict(row)
    if not row.get("ts"):
        row["ts"] = _now_iso()
    values = [_fmt(row.get(k, "")) for k in HEADER]

    with _THREAD_LOCK:
        with open(path, "a+", newline="", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.seek(0)
                existing = f.read()
                n = _count_data_rows(existing)
                writer = csv.writer(f)
                if n == 0 and not existing.strip():
                    writer.writerow(HEADER)
                writer.writerow(values)
                f.flush()
                os.fsync(f.fileno())
                return n + 1
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def iter_rows() -> Iterator[Dict[str, str]]:
    """逐行读取台账（跳过表头）；文件不存在 → 不产出。"""
    path = ledger_path()
    if not path.is_file():
        return
    with open(path, "r", newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        try:
            header = next(reader)
        except StopIteration:
            return
        if not header or header[0] != HEADER[0]:
            # 兼容无表头/异表头文件：按固定 HEADER 解析
            header = HEADER
            f.seek(0)
            reader = csv.reader(f)
        for row in reader:
            if not any(c.strip() for c in row):
                continue
            d: Dict[str, str] = {}
            for i, key in enumerate(header):
                d[key] = row[i] if i < len(row) else ""
            for key in HEADER:
                d.setdefault(key, "")
            yield d


def find(source_url: Optional[str] = None, video_id: Optional[str] = None) -> List[Dict[str, str]]:
    """按 source_url / video_id 查找，返回全部匹配行（列表）。"""
    out: List[Dict[str, str]] = []
    for row in iter_rows():
        if source_url is not None and row.get("source_url") != source_url:
            continue
        if video_id is not None and row.get("video_id") != video_id:
            continue
        if source_url is None and video_id is None:
            continue
        out.append(row)
    return out


def _row_date(ts: str):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def count_today(account: str, date: Optional[Any] = None,
                include_failed: bool = False) -> int:
    """统计某账号在指定日期（默认本地今天）的**真实发布**条数。

    只统计 ``status ∈ {published, scheduled}`` 的行（``failed`` / ``dry-run`` /
    空 status 不计入额度）。``include_failed=True`` 时额外把 ``failed`` 行计入，
    仅供测试/诊断使用。
    """
    if date is None:
        target = datetime.now().astimezone().date()
    elif isinstance(date, str):
        target = datetime.fromisoformat(date).date()
    elif isinstance(date, datetime):
        target = date.date()
    else:
        target = date  # date 对象
    counted = COUNTED_STATUSES + (("failed",) if include_failed else ())
    n = 0
    for row in iter_rows():
        if row.get("account") != account:
            continue
        if _row_date(row.get("ts", "")) != target:
            continue
        if (row.get("status") or "").strip().lower() in counted:
            n += 1
    return n


def summary(account: Optional[str] = None, days: int = 30) -> Dict[str, Any]:
    """近 ``days`` 天的台账汇总（可按账号过滤）。"""
    cutoff = datetime.now().astimezone() - timedelta(days=days)
    by_status: Dict[str, int] = {}
    by_account: Dict[str, int] = {}
    total = 0
    for row in iter_rows():
        if account and row.get("account") != account:
            continue
        ts = row.get("ts", "")
        try:
            when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            when = None
        if when is not None and when.tzinfo is None:
            when = when.replace(tzinfo=datetime.now().astimezone().tzinfo)
        if when is not None and when < cutoff:
            continue
        total += 1
        by_status[row.get("status", "")] = by_status.get(row.get("status", ""), 0) + 1
        acct = row.get("account", "")
        by_account[acct] = by_account.get(acct, 0) + 1
    return dict(
        days=days,
        account=account,
        total=total,
        by_status=by_status,
        by_account=by_account,
    )
