#!/usr/bin/env bash
# youtube_token_refresh.sh — OAuth token 自动刷新

YOUTUBE_DIR="${YOUTUBE_DIR:-$HOME/.hermes/youtube}"
TOKEN_FILE="$YOUTUBE_DIR/request.token"
SECRETS_FILE="$YOUTUBE_DIR/video_uploader.json"

[ ! -f "$TOKEN_FILE" ] && { echo "❌ Token 不存在: $TOKEN_FILE" >&2; exit 1; }
[ ! -f "$SECRETS_FILE" ] && { echo "❌ 凭据不存在: $SECRETS_FILE" >&2; exit 1; }

# 读取 client_id / client_secret
read_secrets() { python3 -c "
import json
d = json.load(open('$SECRETS_FILE'))['installed']
print(d['client_id']); print(d['client_secret']); print(d.get('token_uri','https://oauth2.googleapis.com/token'))
"; }
{ read -r CLIENT_ID; read -r CLIENT_SECRET; read -r TOKEN_URI; } < <(read_secrets)

# 检查过期
EXPIRY_RAW=$(python3 -c "import json,time; d=json.load(open('$TOKEN_FILE')); v=d.get('expiry',0); print(int(v) if isinstance(v,(int,float)) else int(__import__('datetime').datetime.fromisoformat(v.replace('Z','+00:00')).timestamp()))" 2>/dev/null) || EXPIRY_RAW=0
[ "$EXPIRY_RAW" -gt "$(( $(date +%s) + 120 ))" ] && exit 0

echo "🔄 刷新 token..." >&2
REFRESH_TOKEN=$(python3 -c "import json; print(json.load(open('$TOKEN_FILE')).get('refresh_token',''))")
[ -z "$REFRESH_TOKEN" ] && { echo "❌ 无 refresh_token" >&2; exit 1; }

RESP=$(curl -s --connect-timeout 10 --max-time 20 -X POST "$TOKEN_URI" -d "client_id=$CLIENT_ID" -d "client_secret=$CLIENT_SECRET" -d "refresh_token=$REFRESH_TOKEN" -d "grant_type=refresh_token")
echo "$RESP" | python3 -c "
import json,sys,time
from datetime import datetime,timezone
d=json.load(sys.stdin)
if 'access_token' in d:
  d['expiry']=datetime.fromtimestamp(time.time()+d.get('expires_in',3599),tz=timezone.utc).isoformat()
  old=json.load(open('$TOKEN_FILE'))
  if 'refresh_token' not in d and 'refresh_token' in old: d['refresh_token']=old['refresh_token']
  json.dump(d,open('$TOKEN_FILE','w'),indent=2)
  print('✅ Token 已刷新')
else:
  print(f'❌ 刷新失败: {d.get(\"error\",\"未知\")}')
  sys.exit(1)
" 2>&1 || echo "❌ Token 刷新失败" >&2
