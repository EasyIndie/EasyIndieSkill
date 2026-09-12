#!/usr/bin/env python3
"""
youtube_token_refresh.py — Refresh YouTube OAuth token(s) using Python urllib.

More reliable than the bash equivalent (youtube_token_refresh.sh) on macOS:
- No shell quoting / heredoc / process-substitution pitfalls
- Consistent JSON handling with explicit error messages
- Works correctly under cron jobs with restricted shells

Usage:
    python3 ~/.hermes/scripts/youtube_token_refresh.py                  # cron：无参数
    python3 scripts/youtube_token_refresh.py --all-accounts             # 显式全部账号
    TOKEN_FILE=/path/request.token python3 .../youtube_token_refresh.py # 显式单文件

Behaviour (v3, 2026-09-12):
- 无参数运行：
    * 若 ``$YT_ACCOUNTS_DIR``（默认 ``$YOUTUBE_DIR/accounts``）下存在至少一个带
      ``request.token`` 的账号 → 刷新**全部账号**（等价于 ``--all-accounts``）。
    * 否则 → 回退旧行为：只刷新 ``$YOUTUBE_DIR/request.token``。
- 显式输入优先级最高、行为不变：``--all-accounts`` 强制遍历全部账号；
  ``TOKEN_FILE`` 环境变量强制只刷新该文件。
- 软链兼容：旧 ``$YOUTUBE_DIR/request.token`` 现为指向账号 token 的软链。候选目标
  按 ``os.path.realpath`` 去重，**绝不重复刷新同一物理文件**；被跳过者在汇总行里
  以「软链 realpath 去重」说明原因。
- ``--json`` 保留机器可读输出（含 skipped 明细）；默认人类可读。

Output contract (cron no_agent 模式把 stdout 直接投递给老板):
- 成功：**一行**汇总，如
  ``✅ token 刷新正常（账号 1/1 个，下次刷新前有效期 ≥ 6h）``
  —— 保留这一行是为了避免历史上的「静默失败 3 周无人知晓」，但同时不刷屏。
- refresh token 剩余寿命 < 24h：输出 ⚠️ + 重授权命令（提前告警，避免静默死亡）。
- 失败：❌ + 明确错误 + 处置建议（invalid_grant → 重授权命令），exit 1。

Implementation choice（同源策略）:
    本脚本存在**两份逐字节相同的副本**：技能目录
    ``skills/media/easyindie/scripts/youtube_token_refresh.py`` 与 cron 实际执行副本
    ``~/.hermes/scripts/youtube_token_refresh.py``。
    这里选择「复制完整实现」而不是「薄包装 import 技能目录」：cron 任务必须能在技能
    目录被移动 / 删除 / 未同步时独立运行，不能依赖 ``sys.path`` 注入和外部 lib。
    代价是改动后需要手工同步两份（本文件即两份内容完全一致）。

Returns:
    exit 0 on success (全部账号刷新或安全跳过)
    exit 1 on any failure
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
# 路径与环境覆盖
# --------------------------------------------------------------------------- #
YOUTUBE_DIR = os.path.expanduser(
    os.environ.get("YOUTUBE_DIR") or "~/.hermes/youtube")
ACCOUNTS_DIR = os.path.expanduser(
    os.environ.get("YT_ACCOUNTS_DIR") or os.path.join(YOUTUBE_DIR, "accounts"))
# 旧版兼容路径（现在通常是软链）
LEGACY_TOKEN_FILE = os.path.join(YOUTUBE_DIR, "request.token")
# TOKEN_FILE / SECRETS_FILE 支持环境覆盖；显式 TOKEN_FILE 时只刷新该文件
TOKEN_FILE = os.path.expanduser(
    os.environ.get("TOKEN_FILE") or os.path.join(YOUTUBE_DIR, "request.token"))
SECRETS_FILE = os.path.expanduser(
    os.environ.get("SECRETS_FILE") or os.path.join(YOUTUBE_DIR, "video_uploader.json"))

RE_AUTH_CMD = "python3 ~/.hermes/youtube/re_auth_youtube.py"

INVALID_GRANT_MSG = (
    "刷新失败 (invalid_grant) — refresh token 已失效/被撤销，重试无效。\n"
    "   根因：本 OAuth 应用 publishing status = Testing → refresh token 固定 7 天寿命（与是否有活动无关）。\n"
    f"   处置：人工一次性重授权 → {RE_AUTH_CMD}\n"
    "   永久修复：Google Cloud Console → OAuth consent screen → Publishing status 改为 In production（token 不再过期）。"
)


class RefreshError(Exception):
    """单个 token 刷新失败（携带可直接展示给人工的错误信息）。"""


# --------------------------------------------------------------------------- #
# 核心：刷新单个 token 文件
# --------------------------------------------------------------------------- #
def _load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _expiry_ts(token):
    raw = token.get("expiry", 0)
    if isinstance(raw, (int, float)):
        return int(raw)
    return int(datetime.fromisoformat(str(raw).replace("Z", "+00:00")).timestamp())


def refresh_one(token_file, secrets_file):
    """刷新单个 token 文件（就地写回）。

    成功返回 dict(ok=True, status, token_file, detail, expiry, refresh_token_hours)，
    status ∈ {"refreshed", "skipped"}。失败抛 RefreshError。
    """
    if not os.path.isfile(token_file):
        raise RefreshError(f"Token 不存在: {token_file}")
    if not os.path.isfile(secrets_file):
        raise RefreshError(f"凭据不存在: {secrets_file}")

    # 1. client secrets（兼容 installed 包裹与扁平两种结构）
    raw = _load_json(secrets_file)
    secrets = raw.get("installed", raw)
    client_id = secrets.get("client_id", "")
    client_secret = secrets.get("client_secret", "")
    token_uri = secrets.get("token_uri", "https://oauth2.googleapis.com/token")
    if not client_id or not client_secret:
        raise RefreshError("client_id 或 client_secret 为空")

    # 2. 现有 token / 过期判断
    old_token = _load_json(token_file)
    try:
        expiry_ts = _expiry_ts(old_token)
    except Exception as e:  # noqa: BLE001 - 展示原始解析错误即可
        raise RefreshError(f"token 中 expiry 无法解析: {e}")

    if expiry_ts > time.time() + 120:
        return dict(ok=True, status="skipped", token_file=token_file,
                    detail="Token 尚未过期，跳过刷新",
                    expiry=old_token.get("expiry"),
                    refresh_token_hours=None)

    refresh_token = old_token.get("refresh_token", "")
    if not refresh_token:
        raise RefreshError(f"无 refresh_token，需要重新 OAuth 授权: {RE_AUTH_CMD}")

    # 3. POST refresh
    data = urllib.parse.urlencode({
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    }).encode()

    req = urllib.request.Request(token_uri, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            new_token = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        # MUST be handled before URLError (HTTPError 是 URLError 子类) —
        # 响应体里才有 Google 的真实 error code。
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:  # noqa: BLE001
            pass
        err = ""
        try:
            err = (json.loads(body) or {}).get("error", "")
        except Exception:  # noqa: BLE001
            pass
        if err == "invalid_grant":
            raise RefreshError(INVALID_GRANT_MSG)
        raise RefreshError(
            f"刷新失败 HTTP {e.code}: {err or body[:300] or '(空响应体)'}")
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError) or "timed out" in str(e.reason).lower():
            raise RefreshError(f"连接 {token_uri} 超时 — Google 服务在当前网络下不可达")
        raise RefreshError(f"HTTP 请求失败: {e}")
    except (json.JSONDecodeError, OSError) as e:
        raise RefreshError(f"响应解析失败: {e}")

    # 4. 写回
    if "access_token" not in new_token:
        error_msg = new_token.get("error", "未知")
        if error_msg == "invalid_grant":
            raise RefreshError(INVALID_GRANT_MSG)
        raise RefreshError(f"刷新失败: {error_msg}")

    new_token["expiry"] = datetime.fromtimestamp(
        time.time() + new_token.get("expires_in", 3599), tz=timezone.utc
    ).isoformat()
    # response 未返回新 refresh_token 时保留旧的
    if "refresh_token" not in new_token and "refresh_token" in old_token:
        new_token["refresh_token"] = old_token["refresh_token"]
    with open(token_file, "w", encoding="utf-8") as f:
        json.dump(new_token, f, indent=2)

    rti = new_token.get("refresh_token_expires_in")
    hours = rti / 3600 if isinstance(rti, (int, float)) and rti > 0 else None
    return dict(ok=True, status="refreshed", token_file=token_file,
                detail=f"Token 已刷新，过期时间: {new_token['expiry']}",
                expiry=new_token["expiry"], refresh_token_hours=hours)


# --------------------------------------------------------------------------- #
# 数账号发现（不依赖技能目录的 lib，保证 cron 副本可独立运行）
# --------------------------------------------------------------------------- #
def _yaml_scalars(text):
    """极简 YAML 顶层标量解析：只取 ``key: value``，够用即可（不解析嵌套/块标量）。"""
    out = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
            v = v[1:-1]
        if v:
            out[k] = v
    return out


def _account_targets():
    """返回带 token 的账号列表 [(name, token_file, secrets_file), ...]（按名字排序）。

    发现规则（对旧版 lib.list_accounts 的等价简化）：
    - 账号目录不存在 → 空列表；
    - ``accounts/<name>/account.yaml`` 里的 ``token_path`` / ``client_secrets`` 优先，
      否则回退 ``<dir>/request.token`` 与 ``$YOUTUBE_DIR/video_uploader.json``；
    - 只有 token 实际存在（``os.path.isfile``）才算「账号」。
    """
    if not os.path.isdir(ACCOUNTS_DIR):
        return []
    secrets_override = os.environ.get("SECRETS_FILE")
    targets = []
    for name in sorted(os.listdir(ACCOUNTS_DIR)):
        adir = os.path.join(ACCOUNTS_DIR, name)
        if not os.path.isdir(adir):
            continue
        prof = os.path.join(adir, "account.yaml")
        scal = {}
        if os.path.isfile(prof):
            try:
                with open(prof, encoding="utf-8") as f:
                    scal = _yaml_scalars(f.read())
            except OSError:
                scal = {}

        token_path = scal.get("token_path", "")
        if token_path:
            token_file = os.path.expanduser(os.path.expandvars(token_path))
            if not os.path.isabs(token_file):
                token_file = os.path.join(adir, token_file)
        else:
            token_file = os.path.join(adir, "request.token")

        if not os.path.isfile(token_file):
            continue

        if secrets_override:
            secrets_file = os.path.expanduser(secrets_override)
        elif scal.get("client_secrets"):
            secrets_file = os.path.expanduser(os.path.expandvars(scal["client_secrets"]))
        else:
            secrets_file = SECRETS_FILE
        targets.append((name, token_file, secrets_file))
    return targets


def _collect_targets(include_legacy=True):
    """汇总账号 token + legacy token，按 realpath 去重。

    返回 (targets, skipped)：targets 为 dict(label/token_file/secrets_file)；
    skipped 为 [(path, reason), ...]，记录被 realpath 去重的软链/重复项。
    """
    seen = {}
    targets = []
    skipped = []

    for name, token_file, secrets_file in _account_targets():
        rp = os.path.realpath(token_file)
        if rp in seen:
            skipped.append(
                (token_file, f"与账号 {seen[rp]} 为同一物理文件（realpath 去重）"))
            continue
        seen[rp] = name
        targets.append(dict(label=name, token_file=token_file,
                            secrets_file=secrets_file))

    # legacy 兼容路径：现在通常是账号 token 的软链
    if include_legacy and os.path.exists(LEGACY_TOKEN_FILE):
        rp = os.path.realpath(LEGACY_TOKEN_FILE)
        if rp in seen:
            skipped.append(
                (LEGACY_TOKEN_FILE,
                 f"软链 → 与账号 {seen[rp]} 为同一物理文件（realpath 去重）"))
        else:
            seen[rp] = "legacy"
            targets.append(dict(label="legacy", token_file=LEGACY_TOKEN_FILE,
                                secrets_file=SECRETS_FILE))

    return targets, skipped


# --------------------------------------------------------------------------- #
# 输出
# --------------------------------------------------------------------------- #
def _to_json(results, skipped):
    return {
        "ok": all(r["ok"] for r in results),
        "count": len(results),
        "accounts": [{
            "account": r["label"],
            "ok": r["ok"],
            "exit_code": 0 if r["ok"] else 1,
            "token_file": r["token_file"],
            "status": r.get("status"),
            "output": r.get("detail") or "",
            "error": r.get("error"),
            "refresh_token_hours": r.get("refresh_token_hours"),
        } for r in results],
        "skipped": [{"path": p, "reason": reason} for p, reason in skipped],
    }


def _print_human(results, skipped):
    failed = [r for r in results if not r["ok"]]
    if failed:
        for r in failed:
            print(f"❌ [{r['label']}] {r['error']}", file=sys.stderr)
        return 1

    total = len(results)
    warnings = [(r["label"], r["refresh_token_hours"]) for r in results
                if r.get("refresh_token_hours") is not None
                and r["refresh_token_hours"] < 24]
    if warnings:
        print(f"⚠️ token 刷新完成，但需尽快重授权（账号 {total}/{total} 个）")
        for label, hours in warnings:
            print(
                f"   [{label}] refresh token 剩余寿命仅 {hours:.1f} 小时"
                f"（Testing 状态固定 7 天寿命）→ 重授权: {RE_AUTH_CMD}")
        return 0

    dup = ""
    if skipped:
        names = "、".join(os.path.basename(p) for p, _ in skipped)
        dup = f"；软链 realpath 去重 {len(skipped)} 个：{names}"
    print(f"✅ token 刷新正常（账号 {total}/{total} 个，下次刷新前有效期 ≥ 6h{dup}）")
    return 0


def refresh_all(as_json=False):
    targets, skipped = _collect_targets()
    if not targets:
        print(f"❌ 未发现任何可刷新账号: {ACCOUNTS_DIR}", file=sys.stderr)
        return 1

    results = []
    for t in targets:
        try:
            r = refresh_one(t["token_file"], t["secrets_file"])
            r["label"] = t["label"]
            results.append(r)
        except RefreshError as e:
            results.append(dict(label=t["label"], ok=False, status="error",
                                token_file=t["token_file"], error=str(e),
                                refresh_token_hours=None))

    if as_json:
        print(json.dumps(_to_json(results, skipped), ensure_ascii=False, indent=2))
        return 0 if all(r["ok"] for r in results) else 1
    return _print_human(results, skipped)


def run_single(token_file, secrets_file, as_json=False):
    """显式单文件模式 / legacy 回退模式：保持旧版可读输出。"""
    try:
        r = refresh_one(token_file, secrets_file)
    except RefreshError as e:
        if as_json:
            print(json.dumps(dict(ok=False, token_file=token_file, error=str(e)),
                             ensure_ascii=False, indent=2))
        else:
            print(f"❌ {e}", file=sys.stderr)
        return 1

    if as_json:
        print(json.dumps(dict(ok=True, token_file=token_file, status=r["status"],
                              refresh_token_hours=r.get("refresh_token_hours"),
                              detail=r["detail"]), ensure_ascii=False, indent=2))
        return 0

    print(f"✅ {r['detail']}")
    if r["status"] == "refreshed":
        hours = r.get("refresh_token_hours")
        if hours is None:
            print("ℹ️ refresh token 无过期时间（应用 In production，长期有效）")
        elif hours < 24:
            print(
                f"⚠️ refresh token 剩余寿命仅 {hours:.1f} 小时"
                f"（Testing 状态固定 7 天寿命）→ 尽快重授权: {RE_AUTH_CMD}",
                file=sys.stderr)
        else:
            print(f"ℹ️ refresh token 剩余寿命 {hours / 24:.1f} 天")
    return 0


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def main(argv=None):
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--all-accounts", action="store_true",
                        help="遍历账号目录逐个刷新 token")
    parser.add_argument("--json", action="store_true",
                        help="输出机器可读 JSON（默认人类可读汇总）")
    args = parser.parse_args(argv)

    # 显式参数优先级最高
    if args.all_accounts:
        return refresh_all(as_json=args.json)
    if os.environ.get("TOKEN_FILE"):
        return run_single(TOKEN_FILE, SECRETS_FILE, as_json=args.json)

    # 无参数默认：有账号 → 全部账号；否则 → legacy 单文件
    if _account_targets():
        return refresh_all(as_json=args.json)
    return run_single(TOKEN_FILE, SECRETS_FILE, as_json=args.json)


if __name__ == "__main__":
    sys.exit(main())
