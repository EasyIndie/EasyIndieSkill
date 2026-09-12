#!/usr/bin/env python3
"""
google_oauth_reauth.py — 通用 Google OAuth 一键重授权（桌面应用 / localhost 回调）

用途：当 refresh token 已失效（invalid_grant）或被撤销，必须重走一次授权时使用。
特点：纯标准库；自动备份旧 token；授权后立刻自测刷新；失败自动回滚。

用法：
    python3 google_oauth_reauth.py                 # 用下面默认值
    OAUTH_PORT=18081 OAUTH_SCOPE="https://www.googleapis.com/auth/youtube.force-ssl" \
    CLIENT_SECRETS_FILE=~/secrets/client.json TOKEN_FILE=~/secrets/token.json \
    python3 google_oauth_reauth.py

环境变量：
    CLIENT_SECRETS_FILE  OAuth 客户端凭据 json（兼容 installed / web 包装与扁平结构）
    TOKEN_FILE           写入新 token 的路径（旧文件会备份为 <TOKEN_FILE>.bak）
    OAUTH_SCOPE          空格分隔的作用域；默认 youtube.force-ssl
    OAUTH_PORT           本地回调端口，默认 18080（须与 Google 控制台登记的 redirect_uri 一致）

⚠️ 只在「必须重授权」时跑（例如 invalid_grant / 首次授权 / Testing→Production 后换发长期 token），
   不要反复跑：重复 OAuth 可能触发 Google 风控。
⚠️ 浏览器必须与脚本在**同一台机器**上（回调是 http://localhost:<port>/）。
"""
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

HOME = os.path.expanduser("~")
CLIENT_SECRETS_FILE = os.path.expanduser(
    os.environ.get("CLIENT_SECRETS_FILE", f"{HOME}/.hermes/youtube/video_uploader.json")
)
TOKEN_FILE = os.path.expanduser(os.environ.get("TOKEN_FILE", f"{HOME}/.hermes/youtube/request.token"))
SCOPE = os.environ.get("OAUTH_SCOPE", "https://www.googleapis.com/auth/youtube.force-ssl")
PORT = int(os.environ.get("OAUTH_PORT", "18080"))

REDIRECT_URI = f"http://localhost:{PORT}/"
TOKEN_URI = "https://oauth2.googleapis.com/token"
AUTH_URI = "https://accounts.google.com/o/oauth2/auth"

if not os.path.exists(CLIENT_SECRETS_FILE):
    sys.exit(f"❌ 凭据不存在: {CLIENT_SECRETS_FILE}")

with open(CLIENT_SECRETS_FILE) as f:
    raw = json.load(f)
s = raw.get("installed") or raw.get("web") or raw
CLIENT_ID, CLIENT_SECRET = s["client_id"], s["client_secret"]
TOKEN_URI = s.get("token_uri", TOKEN_URI)

result = {}


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        code = q.get("code", [None])[0]
        if not code:
            err = q.get("error", ["no_code"])[0]
            result["error"] = err
            self.send_response(400)
            self.end_headers()
            self.wfile.write(f"OAuth error: {err}".encode())
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        data = urllib.parse.urlencode(dict(
            code=code, client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
            redirect_uri=REDIRECT_URI, grant_type="authorization_code")).encode()
        try:
            td = json.loads(urllib.request.urlopen(
                urllib.request.Request(TOKEN_URI, data=data), timeout=30).read())
        except Exception as e:  # noqa: BLE001
            result["error"] = f"token exchange failed: {e}"
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"token exchange failed, check terminal")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if "access_token" not in td:
            result["error"] = f"exchange response missing access_token: {td}"
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"exchange failed, check terminal")
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        td["expiry"] = datetime.fromtimestamp(
            time.time() + td.get("expires_in", 3599), tz=timezone.utc).isoformat()
        os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            json.dump(td, f, indent=2)
        result["token"] = td
        self.send_response(200)
        self.end_headers()
        self.wfile.write("Auth complete! 可以关闭此窗口。".encode())
        threading.Thread(target=self.server.shutdown, daemon=True).start()

    def log_message(self, *a):  # 静音访问日志
        pass


def verify_refresh(td):
    """用新 refresh token 试刷新一次；同时判断是否为长期有效 token。"""
    rt = td.get("refresh_token")
    if not rt:
        return "⚠️ 响应无 refresh_token（未加 prompt=consent，或该账号此前已授权）"
    data = urllib.parse.urlencode(dict(
        client_id=CLIENT_ID, client_secret=CLIENT_SECRET,
        refresh_token=rt, grant_type="refresh_token")).encode()
    try:
        r = json.loads(urllib.request.urlopen(
            urllib.request.Request(TOKEN_URI, data=data), timeout=30).read())
    except Exception as e:  # noqa: BLE001
        return f"❌ 刷新验证异常: {e}"
    if "access_token" not in r:
        return f"❌ 刷新验证失败: {r.get('error', r)}"
    if "refresh_token_expires_in" in r:
        h = r["refresh_token_expires_in"] / 3600
        return (f"⚠️ 刷新可用，但响应仍带 refresh_token_expires_in ≈ {h:.1f}h "
                f"→ 应用仍在 Testing（refresh token 会周期过期）；"
                f"请把 OAuth consent screen 的 Publishing status 改为 In production")
    return "✅ 刷新验证通过，且 refresh token 无过期时间（In production，长期有效）"


if __name__ == "__main__":
    if os.path.exists(TOKEN_FILE):
        os.replace(TOKEN_FILE, TOKEN_FILE + ".bak")
        print("ℹ️ 旧 token 已备份为 <TOKEN_FILE>.bak")

    params = urllib.parse.urlencode(dict(
        client_id=CLIENT_ID, redirect_uri=REDIRECT_URI, scope=SCOPE,
        response_type="code", access_type="offline", prompt="consent"))
    print("=" * 70)
    print("1) 在浏览器打开下面的授权链接（prompt=consent 强制签发新 refresh token）:")
    print(f"{AUTH_URI}?{params}")
    print("2) 用目标账号登录并点「允许」（未验证应用 → 高级 → 继续前往）")
    print(f"3) 必须在本机浏览器操作（回调 = {REDIRECT_URI}）；只点一次，避免触发风控")
    print("=" * 70)
    sys.stdout.flush()

    try:
        server = HTTPServer(("", PORT), Handler)
    except OSError as e:
        sys.exit(f"❌ 端口 {PORT} 不可用: {e}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    server.server_close()

    if result.get("error"):
        print(f"❌ 授权失败: {result['error']}")
        if os.path.exists(TOKEN_FILE + ".bak"):
            os.replace(TOKEN_FILE + ".bak", TOKEN_FILE)
            print("ℹ️ 已回滚旧 token")
        sys.exit(1)

    td = result.get("token")
    if not td:
        sys.exit("❌ 未收到授权码，token 未保存")
    print(f"✅ 新 token 已保存: {TOKEN_FILE}")
    print(f"   scope : {td.get('scope', '?')}")
    print(f"   expiry: {td.get('expiry', '?')}")
    print(verify_refresh(td))
