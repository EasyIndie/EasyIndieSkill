# curl Exit Codes for OAuth Token Refresh Diagnostics

## Purpose

Quickly distinguish the root cause when a token refresh fails. Knowing the exact curl exit code avoids misdiagnosis between network restriction vs. bad credentials vs. service outage.

## Exit Code Reference (OAuth-Relevant Subset)

| Code | Symbol | Meaning | OAuth Context |
|------|--------|---------|---------------|
| 0 | — | Success | Response received. Examine body for `access_token` or `error` field |
| 7 | CURLE_COULDNT_CONNECT | Connection refused | DNS resolves but port 443 is closed / firewall active / service down |
| **28** | **CURLE_OPERATION_TIMEDOUT** | **Connection or transfer timeout** | **Most common in cron/GFW environments. Google OAuth endpoint unreachable.** The `--connect-timeout` (10s) or `--max-time` (20s) expired with no TCP handshake. |
| 35 | CURLE_SSL_CONNECT_ERROR | TLS handshake failed | MITM proxy / outdated CA bundle / SNI mismatch |
| 52 | CURLE_GOT_NOTHING | Server returned nothing (empty reply) | Load balancer or proxy closed connection without any response |
| 55 | CURLE_SEND_ERROR | Failure sending network data | Mid-stream connection reset — unstable network |
| 56 | CURLE_RECV_ERROR | Failure receiving network data | Connection dropped mid-response |

## How to Check

```bash
# Run the actual refresh request and capture exit code
curl -s --connect-timeout 10 --max-time 20 -X POST "https://oauth2.googleapis.com/token" \
  -d "client_id=..." -d "client_secret=..." \
  -d "refresh_token=..." -d "grant_type=refresh_token" \
  -o /tmp/oauth_resp.json -w "\nEXIT_CODE:%{http_code}\n"
echo "curl_exit: $?"

# Quick connectivity test (no secrets needed)
curl -s --connect-timeout 5 --max-time 10 \
  "https://oauth2.googleapis.com/token" \
  -d "grant_type=refresh_token&client_id=test&client_secret=test&refresh_token=test" \
  -o /dev/null -w "%{http_code}\n"
echo "curl_exit: $?"
```

## Distinguishing Failure Types (Cron Session, July 2026)

| Test | Command | Expected on healthy network | Observed in cron |
|------|---------|---------------------------|------------------|
| Google OAuth | `curl https://oauth2.googleapis.com/token` | HTTP 400 ("invalid_grant" body) | **Exit 28** (timeout, empty body) |
| GitHub API | `curl https://api.github.com` | HTTP 200 | HTTP 200 ✅ |
| Baidu | `curl https://www.baidu.com` | HTTP 200 | Varies |

**Pattern**: Exit 28 on Google + healthy responses to other endpoints = **selective Google blocking**, not general network failure.
