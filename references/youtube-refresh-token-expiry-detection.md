# Refresh Token Expiry Detection

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

## Key Insights

1. **Empty curl response ≠ JSON error the script expects**: When network is unreachable, curl returns nothing. The script pipes this empty response to `python3 -c` for JSON parsing, which fails with `JSONDecodeError`. The error message `❌ 刷新失败` comes from the script's fallback `|| echo "❌ Token 刷新失败"`, not from the curl itself.

2. **Refresh token has its own expiry**: `refresh_token_expires_in` in the token file indicates how long the refresh token is valid. For this token it was ~2.7 days. If the cronjob fails continuously for >3 days, the refresh token becomes permanently invalid.

3. **Selective network blocking**: Google OAuth endpoints timed out, but `api.github.com` worked fine. This means it's a selective Google block, not a general network failure. Proxy/VPN is needed specifically for Google services.

4. **Silent cron decay**: Without monitoring, a token can silently expire and then the refresh token also expires, requiring a full re-auth instead of just a retry.
