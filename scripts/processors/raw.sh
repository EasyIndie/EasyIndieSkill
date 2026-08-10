#!/bin/bash
# raw.sh — 原样下载
info "=== 原样下载 ==="
download_video "$URL" "$VIDEO_ID" "$OUTDIR" || return 1
PROCESSED_FILE="$DOWNLOADED_FILE"
success "下载完成: $(basename "$PROCESSED_FILE")"
