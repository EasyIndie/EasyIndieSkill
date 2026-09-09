#!/usr/bin/env python3
"""
youtube_token_refresh.py — Refresh YouTube OAuth token using Python urllib.

More reliable than the bash equivalent (youtube_token_refresh.sh) on macOS:
- No shell quoting / heredoc / process-substitution pitfalls
- Consistent JSON handling with explicit error messages
- Works correctly under cron jobs with restricted shells

Usage:
    python3 ~/.hermes/skills/media/youtube-carry-workflow/scripts/youtube_token_refresh.py

Environment:
    YOUTUBE_DIR  — override default ($HOME/.hermes/youtube)

Returns:
    exit 0 + "✅ Token refreshed" on success
    exit 1 + "❌ ..." on any failure
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
        die("无 refresh_token，需要重新 OAuth 授权")

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
    else:
        error_msg = new_token.get("error", "未知")
        if error_msg == "invalid_grant":
            die(f"刷新失败 ({error_msg}) — refresh token 已过期，需要重新 OAuth 授权")
        die(f"刷新失败: {error_msg}")


if __name__ == "__main__":
    main()
