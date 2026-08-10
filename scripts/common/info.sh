#!/bin/bash
# info.sh — 信息提取函数

get_video_title() { yt-dlp --cookies-from-browser safari --js-runtimes node --print "title" "$1" 2>/dev/null; }
get_duration_sec() { yt-dlp --cookies-from-browser safari --js-runtimes node --print "duration" "$1" 2>/dev/null; }
get_file_duration() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1" 2>/dev/null | cut -d. -f1; }
get_file_size() { stat -f%z "$1" 2>/dev/null || stat -c%s "$1" 2>/dev/null || echo "0"; }
