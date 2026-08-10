#!/bin/bash
# download.sh — 下载函数
# 设置全局变量: DOWNLOADED_FILE

download_video() {
  local url="$1" video_id="$2" outdir="$3" format="${4:-bestvideo+bestaudio/best}"
  yt-dlp --cookies-from-browser safari --js-runtimes node \
    -f "$format" -o "$outdir/${video_id}_source.%(ext)s" \
    --print after_move:filepath --merge-output-format mp4 "$url" \
    2>&1 | tee /tmp/ytdlp_${video_id}.txt
  DOWNLOADED_FILE=$(grep -E '\.(webm|opus|mp4|mkv|m4a)$' /tmp/ytdlp_${video_id}.txt | tail -1)
  [ -z "$DOWNLOADED_FILE" ] && DOWNLOADED_FILE=$(ls -t "$outdir"/${video_id}_source.* 2>/dev/null | head -1)
  [ -f "$DOWNLOADED_FILE" ] && return 0 || return 1
}

download_audio_only() {
  local url="$1" video_id="$2" outdir="$3"
  yt-dlp --cookies-from-browser safari --js-runtimes node \
    -f "bestaudio[acodec=opus]" -o "$outdir/${video_id}_source.%(ext)s" \
    --print after_move:filepath "$url" 2>&1 | tee /tmp/ytdlp_${video_id}.txt
  DOWNLOADED_FILE=$(grep -E '\.(webm|opus)$' /tmp/ytdlp_${video_id}.txt | tail -1)
  [ -z "$DOWNLOADED_FILE" ] && DOWNLOADED_FILE=$(ls -t "$outdir"/${video_id}_source.* 2>/dev/null | head -1)
  [ -f "$DOWNLOADED_FILE" ] && return 0 || return 1
}
