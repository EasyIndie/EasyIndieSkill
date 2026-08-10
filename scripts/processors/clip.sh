#!/bin/bash
# clip.sh — 截取片段
# 参数: -ss START [-to END | -t DUR]
info "=== 截取模式 ==="
download_video "$URL" "$VIDEO_ID" "$OUTDIR" || return 1
CLIP_FILE="${OUTDIR}/${VIDEO_ID}_clip.mp4"
while [ $# -gt 0 ]; do
  case "$1" in -ss|-to|-t) CLIP_OPTS="$CLIP_OPTS $1 $2"; shift ;; esac; shift
done
ffmpeg -y $CLIP_OPTS -i "$DOWNLOADED_FILE" -c:v libx264 -crf 22 -preset fast \
  -c:a aac -b:a 128k -movflags +faststart "$CLIP_FILE" 2>&1
PROCESSED_FILE="$CLIP_FILE"
rm -f "$DOWNLOADED_FILE"
success "截取完成: $(basename "$PROCESSED_FILE")"
