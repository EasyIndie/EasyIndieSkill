#!/bin/bash
# fake_lark_cli.sh — 离线测试用 lark-cli 假实现（绝不联网、绝不下载真实资源）。
#
# 支持两个子命令：
#   im +chat-messages-list          输出固定 JSON（3 条消息，时间相对当前时刻）
#   im +messages-resources-download 解析 --output，在当前工作目录写出非空文件
#
# 环境变量：
#   FAKE_LARK_INJECT_FAIL=1  让 file 消息的 file_key 含 "FAIL"，触发桩的下载失败
set -u

sub=""
for a in "$@"; do
  case "$a" in
    +chat-messages-list) sub=list ;;
    +messages-resources-download) sub=download ;;
  esac
done

if [ "$sub" = "list" ]; then
  now=$(date +%s)
  t1=$(( (now - 300) * 1000 ))
  t2=$(( (now - 600) * 1000 ))
  t3=$(( (now - 7200) * 1000 ))
  file_key="file_v3_FAKE0001"
  if [ -n "${FAKE_LARK_INJECT_FAIL:-}" ]; then
    file_key="file_v3_FAIL0001"
  fi
  cat <<'EOF' | sed -e "s/__T1__/${t1}/" -e "s/__T2__/${t2}/" -e "s/__T3__/${t3}/" -e "s/__FK__/${file_key}/"
{"ok": true, "data": {"messages": [
  {"message_id": "om_test_file_0001", "msg_type": "file", "create_time": "__T1__", "content": "{\"file_key\": \"__FK__\", \"file_name\": \"Report Final.pdf\"}"},
  {"message_id": "om_test_media_0002", "msg_type": "media", "create_time": "__T2__", "content": "<video key=\"file_v3_FAKE0002\" name=\"clip.MOV\" duration=\"90s\" cover_image_key=\"img_v3_COVER02\"/>"},
  {"message_id": "om_test_text_0003", "msg_type": "text", "create_time": "__T3__", "content": "{\"text\": \"hello\"}"}
]}}
EOF
  exit 0
fi

if [ "$sub" = "download" ]; then
  out=""
  key=""
  type="file"
  while [ $# -gt 0 ]; do
    case "$1" in
      --output) out="${2:-}"; shift 2 ;;
      --file-key) key="${2:-}"; shift 2 ;;
      --type) type="${2:-}"; shift 2 ;;
      *) shift ;;
    esac
  done

  if [ -z "$out" ]; then
    echo '{"ok": false, "error": "missing --output"}' >&2
    exit 1
  fi
  case "$out" in
    /*|*..*)
      echo '{"ok": false, "error": "absolute or traversal path refused"}' >&2
      exit 1
      ;;
  esac
  case "$key" in
    *FAIL*)
      echo '{"ok": false, "error": "simulated download failure"}' >&2
      exit 1
      ;;
  esac

  mkdir -p "$(dirname "$out")" 2>/dev/null || true
  printf '%s' "$key" > "$out" || exit 1
  echo '{"ok": true}'
  exit 0
fi

echo '{"ok": false, "error": "unknown subcommand"}' >&2
exit 1
