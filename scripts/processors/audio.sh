#!/bin/bash
# audio.sh — 提取 MP3
info "=== 音频提取 ==="
download_audio_only "$URL" "$VIDEO_ID" "$OUTDIR" || return 1
MP3_FILE="${OUTDIR}/${VIDEO_ID}_audio.mp3"
ffmpeg -y -i "$DOWNLOADED_FILE" -vn -c:a libmp3lame -b:a 192k "$MP3_FILE" 2>&1
PROCESSED_FILE="$MP3_FILE"
rm -f "$DOWNLOADED_FILE"
success "音频提取完成: $(basename "$PROCESSED_FILE")"
