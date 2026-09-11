# Refresh Token Expiry Detection

## ✅ 根因定论（2026-09-12 实测确认，覆盖早期「寿命 ~2.7 天」的误判）

**refresh token 的寿命 = 固定 7 天（604800 秒），因为该 OAuth 应用的
`Publishing status = Testing`。** 与「是否有活动」「cron 刷新频率」完全无关
（Google 规则：外部用户类型 + 发布状态 Testing 的应用，签发的 refresh token 固定 7 天过期）。

证据链（同一把 refresh token 的三次快照）：

| 快照 | `refresh_token_expires_in` | 反推签发时刻 | 实际死亡时刻 |
|:--|:--|:--|:--|
| `request_broad.token`（6-30 10:45 写入） | **604799**（≈604800 = 恰好 7 天） | 6-30 10:45 | ~7-07 |
| `request.token.bak`（7-04 前的旧 token） | 232893（≈2.7 天 *剩余*） | 6-30 10:45（430 天秒倒推） | ~7-07 |
| `request.token`（8-19 06:00 最后一次成功刷新） | 16281（≈4.5 小时 *剩余*） | ~8-12 10:31 | ~8-19 10:31 |

死点与失败时刻对得上：最后一次成功刷新 8-19 06:00 → 首次 400 出现在 **8-19 12:00**。
早期文档把「剩余值 232893 ≈ 2.7 天」误读成「寿命 2.7 天」——那是倒计时读数，不是寿命。

**因此每次重授权只能买到 7 天**（8-12 重授权 → 8-19 又死），是本任务反复失效的唯一根因。

### 两种修法

| 方案 | 操作 | 效果 |
|:--|:--|:--|
| ⭐ 永久修复（推荐） | Google Cloud Console → APIs & Services → OAuth consent screen → **Publishing status: In production** | refresh token **不再过期**，一次性授权真正常驻（未验证应用仅显示警告页，个人自用无碍） |
| 临时兜底 | 每 ≤7 天跑一次 `python3 ~/.hermes/youtube/re_auth_youtube.py` | 只能续 7 天，且是浏览器交互流程，违背「一次性授权」原则 |

### 脚本已加固（v2，2026-09-12）

`scripts/youtube_token_refresh.py`：
- `HTTPError` 单独捕获并**读取响应体** → 报出 Google 真实 error code。
  （旧版把 `HTTPError` 当 `URLError` 处理，只打印 `HTTP Error 400`，看日志根本看不出 `invalid_grant` —— 连续 6 次失败都因此无法定位。）
- `invalid_grant` 分支直接输出根因 + 重授权命令 + 永久修复路径。
- 每次刷新成功后打印 refresh token 剩余寿命，**<24h 提前告警**（避免再次静默死亡）。

## Session Context

Cronjob running `youtube_token_refresh.sh` produced:
- Script output: `❌ 刷新失败` with `json.decoder.JSONDecodeError: Expecting value: line 2 column 1 (char 1)`
- Root cause: curl to `https://oauth2.googleapis.com/token` returned **empty response** (connection timeout), not JSON
- Token file existed and was valid JSON, but token had expired 4 days ago

## Token File State (2026-07-08)

```json
{
  "access_token": "...",
  "expires_in": 3599,
  "scope": "https://www.googleapis.com/auth/youtube.force-ssl",
  "token_type": "Bearer",
  "refresh_token_expires_in": 232893,
  "expiry": "2026-07-04T11:03:27.368367+00:00",
  "refresh_token": "1//..."
}
```

- `expiry`: 2026-07-04 (expired ~4 days ago when checked on 2026-07-08)
- `refresh_token_expires_in`: 232893 seconds ≈ **2.7 days**

## Diagnostic Commands

```bash
# Check token expiry
TOKEN_FILE="$HOME/.hermes/youtube/request.token"
python3 -c "import json; d=json.load(open('$TOKEN_FILE')); print('expiry:', d.get('expiry'))"
python3 -c "import json; d=json.load(open('$TOKEN_FILE')); print('refresh_token_expires_in:', d.get('refresh_token_expires_in'))"

# Check if refresh token is present
python3 -c "import json; d=json.load(open('$TOKEN_FILE')); print('has_refresh:', bool(d.get('refresh_token','')))"

# Test network reachability
curl -s --connect-timeout 5 --max-time 10 "https://oauth2.googleapis.com/token" -d "grant_type=refresh_token&client_id=test&client_secret=test&refresh_token=test" -o /dev/null -w "%{http_code}"  # timeout = unreachable
curl -s --connect-timeout 5 --max-time 10 "https://api.github.com" -o /dev/null -w "%{http_code}"  # should return 200 if network otherwise OK

# Check proxy env
echo "HTTP_PROXY=$HTTP_PROXY"; echo "HTTPS_PROXY=$HTTPS_PROXY"
```

## invalid_grant ≠ network failure (2026-08-03)

Second incident: script printed `❌ 刷新失败: invalid_grant` — this is a **real JSON error from Google**, not an empty response. Root cause: refresh token itself permanently expired (its `refresh_token_expires_in` ≈ 2.7 days ran out ~Jul 7; token file last refreshed Jul 4). Network was fine.

- `invalid_grant` = refresh token revoked/expired → **cannot be fixed by retry**, must run full re-auth: `python3 ~/.hermes/youtube/re_auth_youtube.py` (backups old token to request.token.bak, serves callback on localhost:18080, auto-verifies new refresh token).
- Third occurrence (2026-08-05): same `invalid_grant`. Token file was STILL the 2026-07-04 one → the Aug 3 re-auth was prepared (script written) but never completed (no request.token.bak, no browser callback). Pattern confirmed: cron can only detect + report; the re-auth step is interactive (browser) and must be run by the user. Do NOT retry refresh on invalid_grant (pointless + suspicious repeated auth traffic).
- Distinguish: curl empty response / JSONDecodeError = network block (needs VPN/proxy); `error: invalid_grant` in JSON = dead refresh token (needs manual re-auth).
- After re-auth, `refresh_token_expires_in` counts down from issuance — cron must refresh successfully within that window (~2.7 days) or the token dies silently again.
- Fourth occurrence (2026-08-06): same `invalid_grant`, token file STILL 2026-07-04 one, still no request.token.bak → re-auth never completed by user. Network verified OK (Google returned real JSON 401 invalid_client for bogus creds). Pattern 100% confirmed: cron detects + reports only; user must run interactive re-auth. Add to the recurring status report each cron run until resolved.
- Fifth occurrence (2026-08-08): same `invalid_grant`, token file STILL 2026-07-04 one, no request.token.bak, network OK (Google endpoint returns HTTP 401 for bogus creds, not timeout). Same conclusion: refresh token permanently dead, re-auth still pending from user.
- **Sixth occurrence (2026-08-19 ~ 08-20, 6 连失败后被暂停)**：老板于 **8-12 前后完成了一次重授权**（`request.token.bak` = 被顶掉的 7-04 旧 token），此后 8-18 18:00、8-19 06:00 刷新正常，**8-19 12:00 起每 6 小时连报 `HTTP Error 400`**，8-20 18:17 人工暂停。脚本脱敏后的 400（未读响应体）掩盖了 `invalid_grant` 真因，我用同样凭据实测复现 → `{"error": "invalid_grant", "error_description": "Bad Request"}`。
  **根因 = 7 天固定寿命到期**（8-12 授权 → 8-19 死亡，完全吻合），不是网络、不是脚本、不是被撤销。
  ⚠️ **运维教训**：该 job `deliver: local` → 6 次失败一次都没通知到人，静默 3 周（8-20 ~ 9-12）无人知晓。
  关键任务必须 `deliver: origin` 或加独立告警通道。

## Key Insights

1. **Empty curl response ≠ JSON error the script expects**: When network is unreachable, curl returns nothing. The script pipes this empty response to `python3 -c` for JSON parsing, which fails with `JSONDecodeError`. The error message `❌ 刷新失败` comes from the script's fallback `|| echo "❌ Token 刷新失败"`, not from the curl itself.

2. **Refresh token 有自己的寿命**：`refresh_token_expires_in` 是**剩余寿命倒计时**（不是总寿命）。
   本应用因 publishing status = Testing，总寿命恒为 **7 天**；cron 若连续失败到超过该窗口仍未重授权，
   refresh token 就永久死亡（必须重走浏览器授权）。见文首「根因定论」。

3. **Selective network blocking**: Google OAuth endpoints timed out, but `api.github.com` worked fine. This means it's a selective Google block, not a general network failure. Proxy/VPN is needed specifically for Google services.

4. **Silent cron decay**: Without monitoring, a token can silently expire and then the refresh token also expires, requiring a full re-auth instead of just a retry.
