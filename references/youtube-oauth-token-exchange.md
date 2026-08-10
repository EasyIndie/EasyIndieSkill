# OAuth 授权码手动交换

当 youtubeuploader 内置 OAuth 弹窗不可用时（远程/VPN/无桌面），用此方法手动换取 token。

## 流程

1. 从 `video_uploader.json` 读取 `client_id` 和 `client_secret`
2. 构造授权 URL 发给用户（Safari 打开）
3. 用户同意后浏览器跳转到 `localhost?code=...`
4. 复制跳转 URL 中的 `code` 参数
5. 用 curl 换 token：

```bash
curl -s -X POST "https://oauth2.googleapis.com/token" \
  -d "code=<授权码>" \
  -d "client_id=<CLIENT_ID>" \
  -d "client_secret=<CLIENT_SECRET>" \
  -d "redirect_uri=http://localhost" \
  -d "grant_type=authorization_code" | python3 -c "
import json, sys, time
from datetime import datetime, timezone
d = json.load(sys.stdin)
d['expiry'] = datetime.fromtimestamp(time.time() + d.get('expires_in', 3599), tz=timezone.utc).isoformat()
json.dump(d, open('$HOME/.hermes/youtube/request.token', 'w'), indent=2)
print('Token saved')
"
```

## 注意事项

- 授权码一次性有效，换成功后不能重复使用
- `expiry` 必须存 RFC3339 格式（Go OAuth2 库要求），不能是 Unix 时间戳
- 保存后后续通过 `youtube_token_refresh.sh` 自动续期，无需再次授权
- redirect_uri 必须与 Google Cloud Console 注册的一致
- **scope 选择**：默认的 `youtube.upload` scope 只能上传，不能修改视频隐私状态。如需改公开/不公开，必须用 `youtube.force-ssl` scope。建议首次授权直接用 `youtube.force-ssl`。如需更换 scope，删除 `request.token` 后用新 scope 重新走一遍 OAuth 流程即可。
- **token 持久化**：授权后用 cronjob 每 6h 自动刷新 token，避免过期。命令：`cronjob action=create schedule="0 */6 * * *" prompt="bash ~/.hermes/skills/media/youtube-carry-workflow/scripts/youtube_token_refresh.sh" deliver=local name="youtube-token-refresh"`
