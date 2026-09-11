#!/usr/bin/env python3
"""
youtube_token_refresh.py — Refresh YouTube OAuth token using Python urllib.

More reliable than the bash equivalent (youtube_token_refresh.sh) on macOS:
- No shell quoting / heredoc / process-substitution pitfalls
- Consistent JSON handling with explicit error messages
- Works correctly under cron jobs with restricted shells

Usage:
    python3 ~/.hermes/skills/media/easyindie/scripts/youtube_token_refresh.py

Environment:
    YOUTUBE_DIR  — override default ($HOME/.hermes/youtube)

Returns:
    exit 0 + "✅ Token refreshed" on success
    exit 1 + "❌ ..." on any failure

v2 (2026-09-12):
- HTTPError 单独处理并读取响应体 → 报出 Google 真实 error code
  （旧版把 HTTPError 当 URLError，只打印 "HTTP Error 400"，看不出 invalid_grant）
- invalid_grant 分支直接给出重授权命令与根因（Testing 发布状态 → refresh token 固定 7 天寿命）
- 每次成功刷新后打印 refresh token 剩余寿命，<24h 提前告警（避免再次静默死亡）
"""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

YOUTUBE_DIR = os.environ.get("YOUTUBE_DIR", os.path.expanduser("~/.hermes/youtube"))
TOKEN_FILE = os.path.join(YOUTUBE_DIR, "request.token")
SECRETS_FILE = os.path.join(YOUTUBE_DIR, "video_uploader.json")

RE_AUTH_CMD = "python3 ~/.hermes/youtube/re_auth_youtube.py"


def die(msg: str) -> None:
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    # 1. Check files exist
    if not os.path.isfile(TOKEN_FILE):
        die(f"Token 不存在: {TOKEN_FILE}")
    if not os.path.isfile(SECRETS_FILE):
        die(f"凭据不存在: {SECRETS_FILE}")

    # 2. Load client secrets
    with open(SECRETS_FILE) as f:
        raw = json.load(f)
    secrets = raw.get("installed", raw)  # tolerate both wrapped and flat
    client_id = secrets.get("client_id", "")
    client_secret = secrets.get("client_secret", "")
    token_uri = secrets.get("token_uri", "https://oauth2.googleapis.com/token")
    if not client_id or not client_secret:
        die("client_id 或 client_secret 为空")

    # 3. Load existing token, check expiry
    with open(TOKEN_FILE) as f:
        old_token = json.load(f)

    expiry_raw = old_token.get("expiry", 0)
    if isinstance(expiry_raw, (int, float)):
        expiry_ts = int(expiry_raw)
    else:
        expiry_ts = int(
            datetime.fromisoformat(str(expiry_raw).replace("Z", "+00:00")).timestamp()
        )

    if expiry_ts > time.time() + 120:
        print("✅ Token 尚未过期，跳过刷新")
        sys.exit(0)

    # 4. Check refresh token exists
    refresh_token = old_token.get("refresh_token", "")
    if not refresh_token:
        die(f"无 refresh_token，需要重新 OAuth 授权: {RE_AUTH_CMD}")

    print("🔄 刷新 token...", file=sys.stderr)

    # 5. POST refresh request
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
        # MUST be handled before URLError (HTTPError is a URLError subclass) —
        # the response body carries Google's real error code.
        body = ""
        try:
            body = e.read().decode("utf-8", "replace")
        except Exception:
            pass
        err = ""
        try:
            err = (json.loads(body) or {}).get("error", "")
        except Exception:
            pass
        if err == "invalid_grant":
            die(
                "刷新失败 (invalid_grant) — refresh token 已失效/被撤销，重试无效。\n"
                "   根因：本 OAuth 应用 publishing status = Testing → refresh token 固定 7 天寿命（与是否有活动无关）。\n"
                f"   处置：人工一次性重授权 → {RE_AUTH_CMD}\n"
                "   永久修复：Google Cloud Console → OAuth consent screen → Publishing status 改为 In production（token 不再过期）。"
            )
        die(f"刷新失败 HTTP {e.code}: {err or body[:300] or '(空响应体)'}")
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError) or "timed out" in str(e.reason).lower():
            die(f"连接 {token_uri} 超时 — Google 服务在当前网络下不可达")
        die(f"HTTP 请求失败: {e}")
    except (json.JSONDecodeError, OSError) as e:
        die(f"响应解析失败: {e}")

    # 6. Process response
    if "access_token" in new_token:
        new_token["expiry"] = datetime.fromtimestamp(
            time.time() + new_token.get("expires_in", 3599), tz=timezone.utc
        ).isoformat()
        # Preserve existing refresh_token if response doesn't return one
        if "refresh_token" not in new_token and "refresh_token" in old_token:
            new_token["refresh_token"] = old_token["refresh_token"]
        with open(TOKEN_FILE, "w") as f:
            json.dump(new_token, f, indent=2)
        print(f"✅ Token 已刷新，过期时间: {new_token['expiry']}")

        # Refresh-token lifetime watchdog: Testing 状态固定 7 天，提前 24h 告警
        rti = new_token.get("refresh_token_expires_in")
        if isinstance(rti, (int, float)) and rti > 0:
            hours = rti / 3600
            if hours < 24:
                print(
                    f"⚠️ refresh token 剩余寿命仅 {hours:.1f} 小时"
                    f"（Testing 状态固定 7 天寿命）→ 尽快重授权: {RE_AUTH_CMD}",
                    file=sys.stderr,
                )
            else:
                print(f"ℹ️ refresh token 剩余寿命 {hours/24:.1f} 天")
    else:
        error_msg = new_token.get("error", "未知")
        if error_msg == "invalid_grant":
            die(
                "刷新失败 (invalid_grant) — refresh token 已过期，需要重新 OAuth 授权: "
                f"{RE_AUTH_CMD}"
            )
        die(f"刷新失败: {error_msg}")


if __name__ == "__main__":
    main()
