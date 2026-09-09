#!/usr/bin/env python3
"""备用 OAuth 授权服务器。从 video_uploader.json 读取凭据。"""
import json, os, sys, threading, urllib.parse, urllib.request
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone

YOUTUBE_DIR = os.path.expanduser("~/.hermes/youtube")
SECRETS_FILE = os.path.join(YOUTUBE_DIR, "video_uploader.json")
TOKEN_FILE = os.path.join(YOUTUBE_DIR, "request.token")
REDIRECT_URI = "http://localhost:18080/"

with open(SECRETS_FILE) as f:
    raw = json.load(f)
    s = raw.get("installed", raw)
CLIENT_ID = s["client_id"]
CLIENT_SECRET = s["client_secret"]
TOKEN_URI = s.get("token_uri", "https://oauth2.googleapis.com/token")

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        code = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("code", [None])[0]
        if not code:
            self.send_response(400); self.end_headers(); self.wfile.write(b"No code")
            return
        data = urllib.parse.urlencode(dict(code=code, client_id=CLIENT_ID, client_secret=CLIENT_SECRET, redirect_uri=REDIRECT_URI, grant_type="authorization_code")).encode()
        req = urllib.request.Request(TOKEN_URI, data=data)
        td = json.loads(urllib.request.urlopen(req).read())
        td["expiry"] = datetime.fromtimestamp(time.time() + td.get("expires_in", 3599), tz=timezone.utc).isoformat()
        json.dump(td, open(TOKEN_FILE, "w"), indent=2)
        print(f"Token saved to {TOKEN_FILE}!")
        self.send_response(200); self.end_headers(); self.wfile.write(b"Auth complete!")
        threading.Thread(target=self.server.shutdown, daemon=True).start()
    def log_message(self, *a): pass

if __name__ == "__main__":
    os.makedirs(YOUTUBE_DIR, exist_ok=True)
    os.path.exists(TOKEN_FILE) and os.remove(TOKEN_FILE)
    print(f"http://localhost:18080/")
    print(f"Auth URL: https://accounts.google.com/o/oauth2/auth?client_id={CLIENT_ID}&redirect_uri=http://localhost:18080/&scope=https://www.googleapis.com/auth/youtube.force-ssl&response_type=code&access_type=offline")
    sys.stdout.flush()
    HTTPServer(("", 18080), Handler).serve_forever()
