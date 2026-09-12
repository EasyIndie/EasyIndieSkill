#!/bin/bash
# fake_youtubeuploader.sh — 离线测试用假上传器（绝不联网、绝不上传）。
#
# 行为：解析 -metaJSONout 参数，写入含假 id 的 JSON，stdout 打印 youtubeuploader
# 真实风格的成功行，供 video_id 正则兜底路径测试。
#
# 环境变量：
#   FAKE_YT_FAIL  设了则模拟失败：stderr 打印该文本并以 FAKE_YT_EXIT（默认 1）退出
#   FAKE_YT_EXIT  失败退出码（默认 1）
set -u

metaout=""
while [ $# -gt 0 ]; do
  case "$1" in
    -metaJSONout) metaout="${2:-}"; shift 2 ;;
    *) shift ;;
  esac
done

if [ -n "${FAKE_YT_FAIL:-}" ]; then
  echo "ERROR: ${FAKE_YT_FAIL}" >&2
  exit "${FAKE_YT_EXIT:-1}"
fi

if [ -n "$metaout" ]; then
  mkdir -p "$(dirname "$metaout")"
  printf '{"id": "dQw4w9WgXcQ", "status": "uploaded"}\n' > "$metaout"
fi

echo "Uploading... video ID: dQw4w9WgXcQ"
exit 0

