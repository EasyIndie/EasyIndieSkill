#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""feishu_fetch_attachment.py — 飞书附件漏抓兜底下载器。

背景
----
飞书机器人走 ``lark_oapi`` SDK 下载附件时，>100MB 会被平台拒绝
（错误码 234037 ``Downloaded file size exceeds limit``），而 Hermes 适配器把该
失败只记 DEBUG 日志，导致消息以空文本进入会话、附件凭空消失。
**同 bot 身份**下 ``lark-cli im +messages-resources-download --type file``
可以下载 106MB（实测成功）。

本脚本从最近的聊天消息里找出「附件消息」，用 ``lark-cli`` 把附件下载落盘，
作为漏抓兜底。

用法::

    python3 scripts/feishu_fetch_attachment.py
        [--chat-id oc_xxx]        # 参数 > FEISHU_CHAT_ID > ~/.hermes/youtube/feishu.yaml
        [--minutes 30]            # 扫描最近 N 分钟（默认 30）；--all 忽略时间窗
        [--limit 50]              # 最多拉取多少条消息
        [--out-dir DIR]           # 默认 ~/.hermes/youtube/inbox/from-feishu/<YYYYMMDD>/
        [--types file,media]      # 默认 file,media；可选 audio,image
        [--with-cover]            # media 消息额外下载封面图
        [--state FILE]            # 默认 ~/.hermes/youtube/feishu_fetched.json
        [--force]                 # 忽略已抓取记录，重新下载
        [--dry-run] [--json] [--quiet]

退出码：0 成功 / 2 参数错 / 3 找不到 lark-cli / 4 列消息失败 /
        5 部分或全部下载失败。

调试时可用环境变量 ``FEISHU_LARK_CLI`` 覆盖 lark-cli 可执行文件路径
（测试即用此注入桩）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_TYPES = "file,media"
DEFAULT_MINUTES = 30
DEFAULT_LIMIT = 50

HOME = Path.home()
FEISHU_YAML = HOME / ".hermes" / "youtube" / "feishu.yaml"
DEFAULT_STATE = HOME / ".hermes" / "youtube" / "feishu_fetched.json"
DEFAULT_INBOX = HOME / ".hermes" / "youtube" / "inbox" / "from-feishu"

# 退出码
EXIT_OK = 0
EXIT_ARGS = 2
EXIT_NO_CLI = 3
EXIT_LIST = 4
EXIT_DOWNLOAD = 5


# --------------------------------------------------------------------------- #
# 小工具
# --------------------------------------------------------------------------- #
def _to_epoch(value):
    """把 create_time（unix 秒/毫秒字符串、数字或 ISO8601）转成 epoch 秒。"""
    if value is None:
        return None
    v = None
    if isinstance(value, (int, float)):
        v = float(value)
    else:
        s = str(value).strip()
        if not s:
            return None
        try:
            v = float(s)
        except ValueError:
            try:
                s2 = s.replace("Z", "+00:00")
                dt = datetime.fromisoformat(s2)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.timestamp()
            except Exception:
                return None
    if v > 1e12:  # 毫秒
        v /= 1000.0
    return v


_ATTR_DQ = re.compile(r'([\w:-]+)\s*=\s*"([^"]*)"')
_ATTR_SQ = re.compile(r"([\w:-]+)\s*=\s*'([^']*)'")


def _xml_attrs(text):
    attrs = {}
    for rx in (_ATTR_DQ, _ATTR_SQ):
        for m in rx.finditer(text):
            attrs.setdefault(m.group(1), m.group(2))
    return attrs


def extract_attachment(msg_type, content):
    """从消息 content 中抽取附件信息。

    支持 JSON 字符串与 XML/伪 XML 两种渲染形态。返回 dict 或 None::

        {"file_key": str|None, "file_name": str|None,
         "cover_image_key": str|None, "image_key": str|None}
    """
    data = None
    if isinstance(content, dict):
        data = content
    elif isinstance(content, str) and content.strip():
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                data = parsed
        except Exception:
            data = None
        if data is None:
            attrs = _xml_attrs(content)
            fk = attrs.get("key") or attrs.get("file_key")
            name = attrs.get("name") or attrs.get("file_name")
            cover = attrs.get("cover_image_key")
            img = attrs.get("image_key")
            if fk or cover or img:
                return {
                    "file_key": fk,
                    "file_name": name,
                    "cover_image_key": cover,
                    "image_key": img,
                }
            return None

    if data is not None:
        fk = data.get("file_key")
        name = data.get("file_name") or data.get("name")
        cover = data.get("cover_image_key")
        img = data.get("image_key")
        if fk or cover or img:
            return {
                "file_key": fk,
                "file_name": name,
                "cover_image_key": cover,
                "image_key": img,
            }
    return None


def sanitize_name(name):
    """净化文件名：去路径分隔符与控制字符，空格转 '-'。"""
    if not name:
        return ""
    name = str(name).replace("\\", "/")
    name = name.split("/")[-1]
    name = "".join(ch for ch in name if ord(ch) >= 32 and ch != "\x7f")
    name = name.replace(" ", "-").strip()
    if name in (".", ".."):
        return ""
    return name


def build_base_name(message_id, file_key, file_name):
    mid8 = (message_id or "")[-8:] or "unknown"
    clean = sanitize_name(file_name)
    if clean:
        return "%s_%s" % (mid8, clean)
    tail = (file_key or "unknown")[-8:]
    return "%s_%s.bin" % (mid8, tail)


def resolve_target(out_dir, base_name, record):
    """决定落盘路径；同名冲突追加 -2、-3。"""
    if record and record.get("path"):
        rp = Path(record["path"])
        if rp.parent == out_dir and rp.name == base_name:
            return rp  # 复用原路径（force 覆盖）
    path = out_dir / base_name
    if not path.exists():
        return path
    stem, ext = os.path.splitext(base_name)
    n = 2
    while True:
        cand = out_dir / ("%s-%d%s" % (stem, n, ext))
        if not cand.exists():
            return cand
        n += 1


def read_default_chat_id(path=FEISHU_YAML):
    """从运行时 feishu.yaml 读取 default_chat_id（极简解析，仅标准库）。"""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, _, val = line.partition(":")
                key = key.strip().lower()
                if key in ("default_chat_id", "chat_id"):
                    val = val.strip().strip('"').strip("'")
                    if val:
                        return val
    except OSError:
        return None
    return None


def resolve_cli():
    override = os.environ.get("FEISHU_LARK_CLI")
    if override:
        return override if os.path.exists(override) else None
    return shutil.which("lark-cli")


# --------------------------------------------------------------------------- #
# lark-cli 调用
# --------------------------------------------------------------------------- #
def list_messages(cli, chat_id, limit):
    cmd = [
        cli, "im", "+chat-messages-list",
        "--chat-id", chat_id,
        "--order", "desc",
        "--page-size", str(min(limit, 50)),
        "--format", "json",
    ]
    with tempfile.TemporaryDirectory(prefix="feishu-fetch-") as tmp:
        proc = subprocess.run(
            cmd, cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    if proc.returncode != 0:
        return None, (err or out or ("exit %d" % proc.returncode)).strip()
    try:
        doc = json.loads(out)
    except Exception:
        return None, "无法解析 chat-messages-list 输出: %s" % (out[:200] or "空输出")
    data = doc.get("data") or {}
    messages = data.get("messages") or doc.get("messages") or []
    if not isinstance(messages, list):
        return None, "messages 字段不是数组"
    return messages, None


def download_resource(cli, out_dir, message_id, file_key, rtype, rel_name):
    """在 cwd=out_dir 下用相对路径下载资源。返回 (Path, err)。"""
    target = out_dir / rel_name
    try:
        if target.exists():
            target.unlink()
    except OSError:
        pass
    cmd = [
        cli, "im", "+messages-resources-download",
        "--message-id", message_id,
        "--file-key", file_key,
        "--type", rtype,
        "--output", rel_name,
    ]
    proc = subprocess.run(
        cmd, cwd=str(out_dir), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or b"").decode("utf-8", "replace").strip()
        return None, (err or ("exit %d" % proc.returncode))
    try:
        size = target.stat().st_size
    except OSError:
        return None, "下载未产生文件: %s" % rel_name
    if size <= 0:
        return None, "下载文件为空: %s" % rel_name
    return target, None


# --------------------------------------------------------------------------- #
# 状态文件
# --------------------------------------------------------------------------- #
def load_state(path):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (OSError, ValueError):
        pass
    return {}


def save_state(path, state):
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(prefix="feishu-state-", suffix=".json", dir="/tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        try:
            os.replace(tmp, str(path))
        except OSError:
            shutil.move(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #
def _emit_json(obj):
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def parse_args(argv):
    p = argparse.ArgumentParser(
        description="飞书附件漏抓兜底下载器（走 lark-cli）",
    )
    p.add_argument("--chat-id")
    p.add_argument("--minutes", type=int, default=DEFAULT_MINUTES)
    p.add_argument("--all", action="store_true")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    p.add_argument("--out-dir")
    p.add_argument("--types", default=DEFAULT_TYPES)
    p.add_argument("--with-cover", action="store_true")
    p.add_argument("--state")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--quiet", action="store_true")
    return p.parse_args(argv)


def _fail(json_mode, code, message):
    if json_mode:
        _emit_json({"ok": False, "error": message})
    else:
        sys.stderr.write(message + "\n")
    return code


def main(argv=None):
    args = parse_args(argv)
    json_mode = bool(args.json)
    quiet = bool(args.quiet)

    # ---- chat_id ----
    chat_id = args.chat_id or os.environ.get("FEISHU_CHAT_ID") or read_default_chat_id()
    if not chat_id:
        return _fail(
            json_mode, EXIT_ARGS,
            "缺少 chat_id：请用 --chat-id、FEISHU_CHAT_ID 或 %s 的 default_chat_id"
            % FEISHU_YAML,
        )

    if args.minutes is not None and args.minutes < 0:
        return _fail(json_mode, EXIT_ARGS, "--minutes 不能为负")
    if args.limit <= 0:
        return _fail(json_mode, EXIT_ARGS, "--limit 必须为正整数")

    types = [t.strip() for t in str(args.types).split(",") if t.strip()]
    if not types:
        return _fail(json_mode, EXIT_ARGS, "--types 不能为空")

    # ---- lark-cli ----
    cli = resolve_cli()
    if not cli:
        return _fail(
            json_mode, EXIT_NO_CLI,
            "找不到 lark-cli（可用 FEISHU_LARK_CLI 指定路径）",
        )

    # ---- 目录 ----
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        out_dir = DEFAULT_INBOX / datetime.now().strftime("%Y%m%d")
    state_path = Path(args.state) if args.state else DEFAULT_STATE

    # ---- 列消息 ----
    messages, err = list_messages(cli, chat_id, args.limit)
    if messages is None:
        return _fail(json_mode, EXIT_LIST, "列消息失败: %s" % err)

    scanned = len(messages)

    # ---- 时间窗 ----
    if args.all:
        cutoff = None
        window_minutes = None
    else:
        window_minutes = args.minutes
        cutoff = datetime.now(timezone.utc).timestamp() - args.minutes * 60.0

    found = []
    downloaded = []
    skipped = []
    failed = []
    would_download = []

    state = load_state(state_path)
    if not args.dry_run:
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return _fail(json_mode, EXIT_ARGS, "无法创建 out-dir: %s" % exc)

    for msg in messages:
        if not isinstance(msg, dict):
            continue
        mtype = msg.get("msg_type")
        if mtype not in types:
            continue
        mid = msg.get("message_id") or ""
        if not mid:
            continue

        # 时间窗过滤
        if cutoff is not None:
            ts = _to_epoch(msg.get("create_time"))
            if ts is not None and ts < cutoff:
                continue

        att = extract_attachment(mtype, msg.get("content"))
        if not att:
            continue
        key = att.get("file_key") or att.get("image_key")
        if not key:
            continue
        rtype = "image" if mtype == "image" else "file"
        entry = {
            "message_id": mid,
            "msg_type": mtype,
            "file_name": att.get("file_name"),
            "file_key": key,
        }
        if att.get("cover_image_key"):
            entry["cover_image_key"] = att["cover_image_key"]
        found.append(entry)

        # 幂等
        rec = state.get(mid)
        if (not args.force and rec and rec.get("file_key") == key
                and rec.get("path")):
            p = Path(rec["path"])
            try:
                same = p.exists() and p.stat().st_size == rec.get("size")
            except OSError:
                same = False
            if same:
                skipped.append({
                    "message_id": mid,
                    "file_name": entry["file_name"],
                    "path": rec["path"],
                    "reason": "already-fetched",
                })
                continue

        if args.dry_run:
            would_download.append(entry)
            continue

        base = build_base_name(mid, key, att.get("file_name"))
        target = resolve_target(out_dir, base, rec)
        ok_path, derr = download_resource(
            cli, out_dir, mid, key, rtype, target.name,
        )
        if ok_path is None:
            failed.append({"message_id": mid, "error": derr or "未知错误"})
            continue
        try:
            size = ok_path.stat().st_size
        except OSError:
            size = 0
        downloaded.append({
            "message_id": mid,
            "file_name": entry["file_name"] or ok_path.name,
            "path": str(ok_path),
            "size_mb": round(size / 1048576.0, 3),
            "file_key": key,
        })
        state[mid] = {
            "file_key": key,
            "path": str(ok_path),
            "size": size,
            "ts": datetime.now(timezone.utc).isoformat(),
        }

        # 封面
        if args.with_cover and att.get("cover_image_key"):
            cover_rel = "%s_cover.jpg" % (mid[-8:] or "unknown")
            cover_target = out_dir / cover_rel
            cpath, cerr = download_resource(
                cli, out_dir, mid, att["cover_image_key"], "image", cover_rel,
            )
            if cpath is None:
                failed.append({
                    "message_id": mid,
                    "error": "封面下载失败: %s" % (cerr or "未知错误"),
                })

    if not args.dry_run:
        save_state(state_path, state)

    ok = not failed
    result = {
        "ok": ok,
        "chat_id": chat_id,
        "scanned": scanned,
        "window_minutes": window_minutes,
        "found": found,
        "downloaded": downloaded,
        "skipped": skipped,
        "failed": failed,
    }
    if args.dry_run:
        result["dry_run"] = True
        result["would_download"] = would_download

    # ---- 输出 ----
    if json_mode:
        _emit_json(result)
    else:
        if not quiet:
            for item in downloaded:
                print("✅ 下载 %s（%.1fMB）→ %s" % (
                    item["file_name"], item["size_mb"], item["path"]))
            for item in skipped:
                print("⏭ 跳过（已抓取） %s → %s" % (
                    item.get("file_name") or item["message_id"],
                    item.get("path", "")))
            for item in failed:
                print("❌ 失败: %s %s" % (item["message_id"], item["error"]))
            if args.dry_run and would_download:
                for item in would_download:
                    print("🔍 待下载 %s（%s）" % (
                        item.get("file_name") or item["message_id"],
                        item["message_id"]))
        print("汇总: scanned=%d found=%d downloaded=%d skipped=%d failed=%d"
              % (scanned, len(found), len(downloaded), len(skipped), len(failed)))

    if failed:
        return EXIT_DOWNLOAD
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
