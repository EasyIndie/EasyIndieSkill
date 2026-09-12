#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""asset_gc.py — EasyIndie work/ 素材定时清理（30 天 LRU + 磁盘水位兜底）。

设计目标（cron 无人值守）：
  * 纯标准库，无第三方依赖；只用 shutil.disk_usage 取磁盘、shutil.rmtree 删除。
  * 幂等、可重复跑；只扫描 <root> 下的直接子目录。
  * 安全门禁：目录名必须匹配 ``^\\d{8}-\\d{4}-`` **且** 目录内含 ``asset.json``
    才允许删除；否则一律跳过。因此即使 ``--root`` 误指到 inbox/ready/published
    等目录，也不会误删（这些目录名不匹配 asset_id 规则）。
  * 无删除且磁盘充足时 stdout 完全为空、exit 0（Hermes cron no_agent 静默契约）。
  * 磁盘低于 --min-free-gb 时进入压力模式：忽略 30 天限制，按最旧优先 LRU
    清理到可用空间 >= max(target_free_gb, min_free_gb)。删除失败/被门禁阻挡时
    只告警、始终 exit 0，避免 cron 把告警误报成脚本故障。

用法示例见 ``-h``。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

GIB = 1024 ** 3
MIB = 1024 ** 2
KIB = 1024

# asset_id 形如 20260912-1532-boss-video
ASSET_NAME_RE = re.compile(r"^\d{8}-\d{4}-")

# 业务盘里"永不自动删"的兄弟目录；即使被 --root 指到也受门禁 2 保护。
PROTECTED_NAMES = frozenset(
    {"inbox", "ready", "published", "covers", "reports", "docs"}
)

EXAMPLES = """\
参数表见上方 options。

安全门禁
  仅当「目录名匹配 ^\\d{8}-\\d{4}- 且目录内含 asset.json」时才可删，
  其余目录（含 inbox/ready/published/covers/reports/docs）一律跳过并计入
  skipped_unsafe。

示例
  python3 scripts/asset_gc.py                       # cron 默认：静默，30 天 LRU
  python3 scripts/asset_gc.py --dry-run --json      # 只看报告，不删
  python3 scripts/asset_gc.py --days 7 --keep 20260101-0000-pinned
  python3 scripts/asset_gc.py --min-free-gb 5 --target-free-gb 10
"""


def default_root() -> Path:
    """默认工作目录：$EASYINDIE_WORK > ~/EasyIndie/work。"""
    env = os.environ.get("EASYINDIE_WORK")
    if env:
        return Path(env).expanduser()
    return Path.home() / "EasyIndie" / "work"


def human_size(n: int) -> str:
    """把字节数格式化成人类可读（KB/MB/GB，1 位小数）。"""
    value = float(n)
    if value >= GIB:
        return f"{value / GIB:.1f} GB"
    if value >= MIB:
        return f"{value / MIB:.1f} MB"
    if value >= KIB:
        return f"{value / KIB:.1f} KB"
    return f"{value:.0f} B"


def dir_size(path: Path) -> int:
    """目录内所有普通文件大小之和（不跟随符号链接目标）。"""
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                st = os.lstat(os.path.join(base, name))
            except OSError:
                continue
            total += st.st_size
    return total


def is_safe_asset(d: Path) -> bool:
    """门禁 2：目录名匹配 asset_id 规则且含 asset.json 才可删。"""
    if not d.is_dir():
        return False
    if d.name in PROTECTED_NAMES or not ASSET_NAME_RE.match(d.name):
        return False
    return (d / "asset.json").is_file()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asset_gc.py",
        description="EasyIndie work/ 素材定时清理：30 天 LRU + 磁盘水位兜底（纯 stdlib）",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--days", type=int, default=30, metavar="N",
                        help="LRU 保留天数，按 asset 目录 mtime 判定（默认 30）")
    parser.add_argument("--root", default=None, metavar="DIR",
                        help="工作目录（默认 $EASYINDIE_WORK 或 ~/EasyIndie/work）")
    parser.add_argument("--min-free-gb", type=float, default=5.0, metavar="X",
                        help="可用空间低于 X GiB 触发磁盘压力模式（默认 5）")
    parser.add_argument("--target-free-gb", type=float, default=10.0, metavar="Y",
                        help="压力模式清理到可用 >= Y GiB（默认 10）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只报告不删除")
    parser.add_argument("--json", action="store_true",
                        help="输出机器可读 JSON")
    parser.add_argument("--keep", action="append", default=[], metavar="NAME",
                        help="白名单目录名（精确匹配），可重复；永不删")
    return parser


def perform(opts: argparse.Namespace) -> dict:
    """执行扫描与清理，返回结构化结果（不做任何打印）。"""
    root = Path(opts.root).expanduser() if opts.root else default_root()
    now = time.time()
    cutoff = now - opts.days * 86400

    result = {
        "root": str(root),
        "days": opts.days,
        "dry_run": bool(opts.dry_run),
        "scanned": 0,
        "skipped_unsafe": 0,
        "kept_whitelist": [],
        "deleted": [],
        "freed_bytes": 0,
        "pressure": False,
        "free_bytes_before": 0,
        "free_bytes_after": 0,
    }

    if not root.is_dir():
        result["error"] = "root-not-found"
        return result

    free_before = shutil.disk_usage(root).free
    min_free = opts.min_free_gb * GIB
    target_free = opts.target_free_gb * GIB
    pressure = free_before < min_free
    # 压力模式下：正常配置 target > min，清理目标即 target；若误把 min 设得
    # 比 target 还大，则以 min 为准，保证"触发即有动作"。
    goal = max(target_free, min_free) if pressure else target_free

    result["pressure"] = pressure
    result["free_bytes_before"] = free_before

    keep = set(opts.keep or [])
    candidates = []
    for d in sorted(root.iterdir(), key=lambda p: p.name):
        if not d.is_dir():
            continue
        result["scanned"] += 1
        if d.name in keep:
            result["kept_whitelist"].append(d.name)
            continue
        if not is_safe_asset(d):
            result["skipped_unsafe"] += 1
            continue
        mtime = d.stat().st_mtime
        candidates.append({
            "path": d,
            "name": d.name,
            "mtime": mtime,
            "age_days": (now - mtime) / 86400.0,
        })

    candidates.sort(key=lambda c: c["mtime"])  # 最旧优先

    freed = 0
    for c in candidates:
        if pressure:
            if free_before + freed >= goal:
                break
            reason = "pressure"
        else:
            if c["mtime"] >= cutoff:
                continue
            reason = "expired"

        size = dir_size(c["path"])
        if not opts.dry_run:
            shutil.rmtree(c["path"])
        freed += size
        result["deleted"].append({
            "name": c["name"],
            "path": str(c["path"]),
            "size_bytes": size,
            "age_days": round(c["age_days"], 2),
            "reason": reason,
        })

    result["freed_bytes"] = freed
    result["free_bytes_after"] = free_before + freed
    return result


def render_text(res: dict, opts: argparse.Namespace) -> list:
    """按输出契约生成人类可读文本行（无删除且磁盘充足时返回空列表）。"""
    if res.get("error"):
        return []

    lines = []
    min_free = opts.min_free_gb * GIB
    free_before = res["free_bytes_before"]
    free_after = res["free_bytes_after"]

    if res["pressure"]:
        lines.append(
            f"⚠️ 磁盘压力模式：可用 {human_size(free_before)} < 阈值 "
            f"{opts.min_free_gb:g} GiB（目标 {opts.target_free_gb:g} GiB）｜ "
            f"清理前 {human_size(free_before)} → 清理后 {human_size(free_after)}"
        )

    if res["deleted"]:
        lines.append(
            f"🧹 素材清理：删除 {len(res['deleted'])} 个"
            f"（释放 {human_size(res['freed_bytes'])}）"
            f"｜ 可用 {human_size(free_after)}"
        )
        for it in res["deleted"]:
            lines.append(
                f"   - {it['name']} ({human_size(it['size_bytes'])}, "
                f"{int(it['age_days'])}天)"
            )

    if res["pressure"] and free_after < min_free:
        lines.append(
            f"⚠️ 磁盘紧张：可用 {human_size(free_after)} 仍低于阈值 "
            f"{opts.min_free_gb:g} GiB（安全门禁/白名单阻挡：跳过 "
            f"{res['skipped_unsafe']} 个，白名单 {len(res['kept_whitelist'])} 个），"
            f"请人工扩容或处理"
        )

    return lines


def to_json(res: dict, opts: argparse.Namespace) -> dict:
    out = {
        "root": res["root"],
        "dry_run": res["dry_run"],
        "days": res["days"],
        "pressure": res["pressure"],
        "min_free_gb": opts.min_free_gb,
        "target_free_gb": opts.target_free_gb,
        "scanned": res["scanned"],
        "deleted": res["deleted"],
        "freed_bytes": res["freed_bytes"],
        "skipped_unsafe": res["skipped_unsafe"],
        "kept_whitelist": res["kept_whitelist"],
        "free_bytes": res["free_bytes_after"],
        "free_bytes_before": res["free_bytes_before"],
        "free_gb": round(res["free_bytes_after"] / GIB, 2),
    }
    if res.get("error"):
        out["error"] = res["error"]
    return out


def main(argv=None) -> int:
    parser = build_parser()
    opts = parser.parse_args(argv)
    res = perform(opts)

    if res.get("error") == "root-not-found":
        print(f"asset_gc: 工作目录不存在，跳过：{res['root']}", file=sys.stderr)
        if opts.json:
            print(json.dumps(to_json(res, opts), ensure_ascii=False, indent=2))
        return 0

    if opts.json:
        print(json.dumps(to_json(res, opts), ensure_ascii=False, indent=2))
    else:
        for line in render_text(res, opts):
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
