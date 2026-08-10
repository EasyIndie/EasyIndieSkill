#!/bin/bash
# init.sh — 环境初始化
# YouTube 搬运工作流共享核心

YOUTUBE_DIR="${YOUTUBE_DIR:-$HOME/.hermes/youtube}"
DEFAULT_OUTDIR="$HOME/Downloads/youtube-carry"

info()    { echo -e "\033[0;34mℹ\033[0m $*"; }
success() { echo -e "\033[0;32m✅\033[0m $*"; }
warn()    { echo -e "\033[1;33m⚠️\033[0m $*"; }
error()   { echo -e "\033[0;31m❌\033[0m $*" >&2; }

fmt_duration() { printf '%d:%02d' $(($1/60)) $(($1%60)); }

get_video_id() {
  echo "$1" | grep -oE '(v=|youtu\.be/)[a-zA-Z0-9_-]+' | sed 's/^v=//;s|^youtu\.be/||'
}

ensure_outdir() { mkdir -p "${1:-$DEFAULT_OUTDIR}"; echo "${1:-$DEFAULT_OUTDIR}"; }

# ---------- 磁盘空间管理 ----------

ensure_disk_space() {
  local outdir="$1"
  local min_free_mb="${MIN_FREE_MB:-${2:-500}}"

  local avail_kb
  avail_kb=$(df -k "$outdir" 2>/dev/null | awk 'NR>1 {print $4}')
  local avail_mb=$(( avail_kb / 1024 ))

  [ "$avail_mb" -ge "$min_free_mb" ] && return 0

  warn "磁盘空间不足: ${avail_mb}MB（需要 ${min_free_mb}MB），按 LRU 清理旧文件..."

  local deleted_any=false
  while [ "$avail_mb" -lt "$min_free_mb" ]; do
    local oldest
    oldest=$(ls -t "$outdir"/*_carry.webm "$outdir"/*_source.mp4 \
             "$outdir"/*_clip.mp4 "$outdir"/*_audio.mp3 \
             "$outdir"/*_source.webm 2>/dev/null | tail -1)
    [ -z "$oldest" ] && break
    rm -f "$oldest"
    info "  已删除: $(basename "$oldest")"
    deleted_any=true
    avail_kb=$(df -k "$outdir" 2>/dev/null | awk 'NR>1 {print $4}')
    avail_mb=$(( avail_kb / 1024 ))
  done

  if [ "$avail_mb" -lt "$min_free_mb" ]; then
    [ "$deleted_any" = true ] && warn "已清空全部工作文件，空间仍不足: ${avail_mb}MB"
    # 打印机器可解析的告警，供 Agent 捕获后通知用户
    echo "DISK_ALERT|工作目录已全部清空，磁盘空间仍不足 ${avail_mb}MB（需 ${min_free_mb}MB），请手动释放"
    return 1
  fi

  info "磁盘空间正常: ${avail_mb}MB 可用"
  return 0
}
