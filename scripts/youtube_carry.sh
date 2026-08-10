#!/bin/bash
# youtube_carry.sh — 统一入口
set -euo pipefail

# 参数解析
BATCH=false; MODE=""
case "${1:-}" in
  --batch) BATCH=true; shift
    [ "${1:-}" = "--file" ] && BATCH_FILE="$2" && shift 2
    MODE="${1:-}"; shift 2>/dev/null || true ;;
  *) MODE="${1:-}"; URL="${2:-}"; shift 2 2>/dev/null || true ;;
esac

# 获取新 skill 路径（兼容新旧两种位置）
SKILL_DIR="${SKILL_DIR:-}"
if [ -z "$SKILL_DIR" ]; then
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
  if [ -d "$SCRIPT_DIR/../SKILL.md" ] || [ -f "$SCRIPT_DIR/../SKILL.md" ]; then
    SKILL_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
  else
    SKILL_DIR="$HOME/.hermes/skills/media/youtube-carry-workflow"
  fi
fi
source "$SKILL_DIR/scripts/common/init.sh"
source "$SKILL_DIR/scripts/common/download.sh"
source "$SKILL_DIR/scripts/common/info.sh"
source "$SKILL_DIR/scripts/common/upload.sh"

# 收集 URLs
URLS=(); CLIP_OPTS=()
if [ "$BATCH" = true ]; then
  if [ -n "${BATCH_FILE:-}" ]; then
    while IFS= read -r line; do URLS+=("$line"); done < "$BATCH_FILE"
    CLIP_OPTS=("$@")
  else
    while [ $# -gt 0 ]; do
      case "$1" in -ss|-to|-t) CLIP_OPTS+=("$1"); shift; CLIP_OPTS+=("${1:-}"); shift 2>/dev/null || true ;;
        *) URLS+=("$1"); shift ;;
      esac
    done
  fi
else
  URLS+=("$URL"); CLIP_OPTS=("$@")
fi

OUTDIR="${OUTDIR:-$(ensure_outdir)}"
URLS_CLEAN=(); for u in "${URLS[@]}"; do [ -n "$u" ] && URLS_CLEAN+=("$u"); done
URLS=("${URLS_CLEAN[@]}")
[ ${#URLS[@]} -eq 0 ] && { error "缺少 URL"; echo "用法: $0 <mode> <url>"; exit 1; }

case "$MODE" in asmr|raw|clip|audio) ;; *) error "未知模式: $MODE (支持: asmr raw clip audio)"; exit 1 ;; esac

BATCH_RESULTS=(); FAIL=0
process_one() {
  local url="$1"; local vid
  vid=$(get_video_id "$url") || { error "无效 URL: $url"; return 1; }
  # 处理前检查磁盘空间，不够则按 LRU 清理旧文件
  ensure_disk_space "$OUTDIR" 500 || return 1
  info "[$vid] $url"
  URL="$url"; VIDEO_ID="$vid"; PROCESSED_FILE=""
  case "$MODE" in
    asmr)  source "$SKILL_DIR/scripts/processors/asmr.sh" || return 1 ;;
    raw)   source "$SKILL_DIR/scripts/processors/raw.sh" || return 1 ;;
    clip)  source "$SKILL_DIR/scripts/processors/clip.sh" "${CLIP_OPTS[@]}" || return 1 ;;
    audio) source "$SKILL_DIR/scripts/processors/audio.sh" || return 1 ;;
  esac
  [ -f "$PROCESSED_FILE" ] || return 1
  BATCH_RESULTS+=("$url|$PROCESSED_FILE")
}

for url in "${URLS[@]}"; do process_one "$url" || { FAIL=$((FAIL+1)); continue; }; done

# 汇总
echo "---"
echo "总数: ${#URLS[@]}, 成功: $(( ${#URLS[@]} - FAIL )), 失败: $FAIL"
for r in "${BATCH_RESULTS[@]+"${BATCH_RESULTS[@]}"}"; do echo "RESULT|${r}"; done
[ $FAIL -eq ${#URLS[@]} ] && exit 1 || exit 0
