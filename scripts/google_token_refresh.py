#!/usr/bin/env python3
"""
google_token_refresh.py — Google OAuth refresh token 自动续期（硬化版，适合 cron no_agent 任务）

相对常见写法的加固点（都是踩过的坑）：
1. HTTPError 单独捕获并**读取响应体** → 报出 Google 真实 error code
   （HTTPError 是 URLError 子类；只 except URLError 会只剩 "HTTP Error 400"，真因被吞）
2. invalid_grant 分支直接给根因 + 重授权命令（重试无意义）
3. 每次成功刷新打印 refresh token 剩余寿命；<24h 提前告警
4. 响应中**没有** refresh_token_expires_in → 明确提示 Production 长期有效

用法：
    python3 google_token_refresh.py
环境变量：
    TOKEN_FILE / CLIENT_SECRETS_FILE（或兼容的 YOUTUBE_DIR 目录）
退出码：0 = 无需刷新 或 刷新成功；1 = 任何失败（cron 会据此告警）
"""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
_yt = os.environ.get("YOUTUBE_DIR", f"{HOME}/.hermes/youtube")
TOKEN_FILE = os.path.expanduser(os.environ.get("TOKEN_FILE", f"{_yt}/request.token"))
SECRETS_FILE = os.path.expanduser(os.environ.get("CLIENT_SECRETS_FILE", f"{_yt}/video_uploader.json"))
RE_AUTH_HINT = "python3 scripts/google_oauth_reauth.py（本技能）或项目内的 re_auth 脚本"


def die(msg):
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    if not os.path.isfile(TOKEN_FILE):
        die(f"Token 不存在: {TOKEN_FILE}")
    if not os.path.isfile(SECRETS_FILE):
        die(f"凭据不存在: {SECRETS_FILE}")

    with open(SECRETS_FILE) as f:
        raw = json.load(f)
    secrets = raw.get("installed") or raw.get("web") or raw
    client_id, client_secret = secrets.get("client_id", ""), secrets.get("client_secret", "")
    token_uri = secrets.get("token_uri", "https://oauth2.googleapis.com/token")
    if not client_id or not client_secret:
        die("client_id 或 client_secret 为空")

    with open(TOKEN_FILE) as f:
        old = json.load(f)
    exp = old.get("expiry", 0)
    exp_ts = int(exp) if isinstance(exp, (int, float)) else int(
        datetime.fromisoformat(str(exp).replace("Z", "+00:00")).timestamp())
    if exp_ts > time.time() + 120:
        print("✅ Token 尚未过期，跳过刷新")
        return

    refresh_token = old.get("refresh_token", "")
    if not refresh_token:
        die(f"无 refresh_token，需要重新授权: {RE_AUTH_HINT}")

    print("🔄 刷新 token...", file=sys.stderr)
    data = urllib.parse.urlencode({
        "client_id": client_id, "client_secret": client_secret,
        "refresh_token": refresh_token, "grant_type": "refresh_token"}).encode()
    req = urllib.request.Request(token_uri, data=data, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            new = json.loads(resp.read())
    except urllib.error.HTTPError as e:          # 必须早于 URLError
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
            die("刷新失败 (invalid_grant) — refresh token 已失效/被撤销，重试无效。\n"
                "   常见根因：应用 Publishing status = Testing → refresh token 固定 7 天寿命。\n"
                f"   处置：人工一次性重授权 → {RE_AUTH_HINT}\n"
                "   永久修复：Google Cloud Console → OAuth consent screen → Publishing status 改 In production。")
        die(f"刷新失败 HTTP {e.code}: {err or body[:300] or '(空响应体)'}")
    except urllib.error.URLError as e:
        if isinstance(e.reason, TimeoutError) or "timed out" in str(e.reason).lower():
            die(f"连接 {token_uri} 超时 — Google 服务当前不可达")
        die(f"HTTP 请求失败: {e}")
    except (json.JSONDecodeError, OSError) as e:
        die(f"响应解析失败: {e}")

    if "access_token" not in new:
        err = new.get("error", "未知")
        if err == "invalid_grant":
            die(f"刷新失败 (invalid_grant) — refresh token 已过期，需重新授权: {RE_AUTH_HINT}")
        die(f"刷新失败: {err}")

    new["expiry"] = datetime.fromtimestamp(
        time.time() + new.get("expires_in", 3599), tz=timezone.utc).isoformat()
    if "refresh_token" not in new and "refresh_token" in old:
        new["refresh_token"] = old["refresh_token"]
    with open(TOKEN_FILE, "w") as f:
        json.dump(new, f, indent=2)
    print(f"✅ Token 已刷新，过期时间: {new['expiry']}")

    rti = new.get("refresh_token_expires_in")
    if isinstance(rti, (int, float)) and rti > 0:
        hours = rti / 3600
        if hours < 24:
            print(f"⚠️ refresh token 剩余寿命仅 {hours:.1f} 小时（Testing 状态固定 7 天寿命）"
                  f"→ 尽快重授权: {RE_AUTH_HINT}", file=sys.stderr)
        else:
            print(f"ℹ️ refresh token 剩余寿命 {hours / 24:.1f} 天")
    else:
        print("ℹ️ refresh token 无过期时间（应用 In production，长期有效）")


if __name__ == "__main__":
    main()
