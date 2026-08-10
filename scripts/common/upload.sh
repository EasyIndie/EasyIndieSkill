#!/bin/bash
# upload.sh — 上传函数

upload_video() {
  local file="$1" title="$2" description="$3" privacy="${4:-unlisted}"
  local secrets="${YOUTUBE_DIR}/video_uploader.json"
  # fallback YOUTUBE_DIR if not set when sourced standalone
  local token="${YOUTUBE_DIR}/request.token"
  [ ! -f "$file" ] && { error "文件不存在: $file"; return 1; }
  [ ! -f "$secrets" ] && { error "OAuth 凭据不存在: $secrets"; return 1; }
  [ -f "$token" ] && source "$SKILL_DIR/scripts/youtube_token_refresh.sh" 2>/dev/null || true
  # fallback error() if sourced standalone (not via youtube_carry.sh's common.sh)
  type error &>/dev/null || error() { echo "❌ $*" >&2; }
  YT_UPLOADER="${YT_UPLOADER:-$(which youtubeuploader 2>/dev/null || echo "$HOME/go/bin/youtubeuploader")}"
  local cache_dir="${YOUTUBE_DIR:-$HOME/.hermes/youtube}"
  "$YT_UPLOADER" -secrets "$secrets" -cache "$cache_dir/request.token" -filename "$file" \
    -title "$title" -description "$description" -privacy "$privacy" 2>&1
}
