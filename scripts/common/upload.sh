#!/bin/bash
# upload.sh — 上传函数（v2：转发到 scripts/youtube_upload.py）
#
# 向后兼容：保留旧签名 upload_video <file> "<title>" "<desc>" [privacy]。
# 新增 upload_video_ex：在前三个参数后原样透传 --account/--tags/--playlist/
#   --publish-at/--thumbnail/--dry-run 等 youtube_upload.py 支持的选项。
#
# 账号：--account-auto 决定（$YT_ACCOUNT 或默认账号）。
# 上传器：YT_UPLOADER 环境变量仍可覆盖（由 python 端读取）。

_yt_upload_python() {
  local py="${YT_UPLOAD_PYTHON:-python3}"
  local skill="${SKILL_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
  "$py" "$skill/scripts/youtube_upload.py" "$@"
}

upload_video() {
  local file="$1" title="$2" description="$3" privacy="${4:-unlisted}"
  upload_video_ex "$file" "$title" "$description" --privacy "$privacy"
}

upload_video_ex() {
  local file="$1" title="$2" description="$3"
  shift 3
  # fallback error() if sourced standalone (not via youtube_carry.sh's common.sh)
  type error &>/dev/null || error() { echo "❌ $*" >&2; }
  [ ! -f "$file" ] && { error "文件不存在: $file"; return 1; }
  _yt_upload_python --account-auto --file "$file" \
    --title "$title" --description "$description" "$@"
}
