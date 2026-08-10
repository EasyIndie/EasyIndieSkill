#!/bin/bash
# asmr.sh — ASMR 黑帧 VP9 + Opus 保留
info "=== ASMR 模式 ==="
download_audio_only "$URL" "$VIDEO_ID" "$OUTDIR" || return 1
AUDIO_DUR=$(get_file_duration "$DOWNLOADED_FILE")
PROCESSED_FILE="${OUTDIR}/${VIDEO_ID}_carry.webm"
ffmpeg -y -f lavfi -i color=c=black:s=1920x1080:d=$((AUDIO_DUR+30)):r=30 \
  -i "$DOWNLOADED_FILE" -map 1:a -map 0:v \
  -c:v libvpx-vp9 -crf 30 -b:v 0 -deadline realtime -cpu-used 5 \
  -c:a copy -shortest "$PROCESSED_FILE" 2>&1
rm -f "$DOWNLOADED_FILE"
success "ASMR 完成: $(basename "$PROCESSED_FILE")"
