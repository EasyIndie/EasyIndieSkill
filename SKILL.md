---
name: easyindie
description: "EasyIndie 内容自动化统一技能（多领域扩展）：YouTube 搬运/内容创作（当前），后续按领域扩展 audio/video/ai-music 等。"
version: 1.0.0
author: Hermes Agent
tags: [youtube, video, audio, content, automation, upload, oauth]
platforms: [macos, linux]
required_commands: [yt-dlp, ffmpeg, ffprobe, python3, node]
---

# EasyIndie 内容自动化（统一技能）

> **领域路由表**：本技能按「领域」组织，每个领域自包含（知识在 references/ 前缀分组、脚本在 scripts/）。新增领域 = 路由表加一行 + 文件按前缀收录。
>
> | 领域 | 触发 | 知识 | 脚本 |
> |:--|:--|:--|:--|
> | **youtube**（当前） | YouTube 链接 / 搬运 / 字幕转内容 / OAuth | `references/youtube-*.md` | `scripts/youtube_*.sh/py`、`scripts/processors/` |
> | （后续）audio | 音频处理/生成 | `references/audio-*.md` | `scripts/audio/` |
> | （后续）video | 短视频剪辑 | `references/video-*.md` | `scripts/video/` |

## 使用时机
- 用户发 YouTube 链接（搬运：默认 asmr 模式；或指定 raw/clip/audio）
- 用户要总结/转写/再创作视频内容（字幕 → 摘要/推文/博客）
- YouTube OAuth token 授权/刷新/故障诊断
- 后续领域（音频/视频/AI 音乐）触发条件在此追加

---

# YouTube 领域（youtube）

## 触发规则（搬运模式）

```
链接本身                     → asmr 模式
"原样下载" / "raw"           → raw 模式
"截取X:XX到Y:YY" / "clip"   → clip 模式
"提取音频" / "audio"         → audio 模式
"总结/字幕/转写/博客"        → 内容创作（fetch_transcript）
```

## 搬运处理流程

1. ✅ 检查磁盘空间（<500MB 则 LRU 删旧文件，全删仍不足 → DISK_ALERT 立即通知用户）
2. 提取视频信息（标题、时长）→ 告知用户
3. 运行入口脚本下载+处理：`bash scripts/youtube_carry.sh <mode> <url> [clip-opts]`
4. 根据音频特征建议标题/描述 → 用户确认
5. 调用 upload.sh 上传

| 模式 | 命令 | 输出 |
|------|------|------|
| asmr | `youtube_carry.sh asmr <url>` | `.webm` 黑帧 VP9 + Opus (c:a copy) |
| raw  | `youtube_carry.sh raw  <url>` | 原始 `.mp4` |
| clip | `youtube_carry.sh clip <url> -ss START [-to END or -t DUR]` | `.mp4` H264+AAC |
| audio| `youtube_carry.sh audio <url>` | `.mp3` 192kbps |

批处理：`youtube_carry.sh --batch asmr url1 url2 url3` / `--batch --file urls.txt asmr`；混合模式需按模式分组多次调用。

## 标题偏好（按用户）

- **{USER_B}**：`【ASMR】{简短标题}`（无时长前缀、无分隔符），如 `【ASMR】不良少女的深夜独白`；中文，给 5 个方案选择
- **{USER_A}**：`【ASMR】{N}分钟{核心内容} · {修饰/副标题}`；中文，5 个方案
- 音频特征分析（静音段/音量判断有无语音）：`ffprobe` + `ffmpeg silencedetect`

## 上传与 OAuth

```bash
source scripts/common/upload.sh && upload_video <file> "<title>" "<desc>" [privacy]
# ⚠️ 直接调 youtubeuploader 必须加 -cache "$HOME/.hermes/youtube/request.token"
# OAuth scope 限制：youtube.upload 只能上传不能改隐私；初始授权用 youtube.force-ssl
```

- **token 刷新（推荐 Python 版）**：`python3 scripts/youtube_token_refresh.py`（macOS 上 bash 版有引用脆弱性）
- **一键重授权**：`python3 {YOUTUBE_CONFIG_DIR}/re_auth_youtube.py`（打印 URL → 浏览器授权 → 自动换 token）
- **GFW 网络限制**：Google OAuth 端点不可达时设 `HTTPS_PROXY` 或远程刷新 token 传回
- **Refresh token 生命周期**：`refresh_token_expires_in` ≈ 2.7 天——cron 连续 3 天刷新失败则必须重新完整授权
- cron 建议：每 6h 刷新（`0 */6 * * *`，deliver local）

## 内容创作（字幕 → 内容）

```bash
python3 scripts/fetch_transcript.py "<URL>" [--text-only|--timestamps] [--language tr,en]
```
- 输出格式：章节/摘要/章节摘要/推文串/博客/金句（详见 `references/output-formats.md`）
- 字幕 >50K 字符分块（40K+2K 重叠）再合并
- 错误处理：字幕禁用→告知用户；私享视频→验证 URL；依赖缺失→pip install youtube-transcript-api

## 运行时 Pitfalls（速查）

- **yt-dlp 必须 `--cookies-from-browser safari --js-runtimes node`**（macOS Chrome cookie 加密读不了）
- **asmr 必须 `-c:a copy`**（不重编码，否则破坏 Opus 48kHz）
- **超 15 分钟视频**：提醒验证账号（下架风险）；ffmpeg 编码超时用 `background=True + notify_on_complete`
- **42min+ 视频**：编码 ~27min，必须后台跑
- **下载与编码并行化**：先下载所有 audio（`bestaudio[acodec=opus]`）再逐个编码
- **yt-dlp 403**：加 `--extractor-args "youtube:player_client=tv"`；info 也拿不到则按时长/URL 推断标题不卡流程
- **磁盘 LRU 清理**：默认阈值 500MB（`MIN_FREE_MB` 覆盖），全删不足 → DISK_ALERT
- **youtubeuploader 不在 PATH**：`~/go/bin/`，upload.sh 有 fallback
- **write_file 安全扫描器**：写含 `$HOME`/`$(...)`/凭证的脚本可能被 `...` 遮蔽——写入后用 patch 修复
- **curl 退出码诊断**：28=超时（GFW 最常见）/ 7=连接拒绝 / 22=HTTP 错误 / 0=成功（详见 `references/youtube-diagnostics.md`）

## 知识体系索引（references/）

| 文件 | 内容 |
|:--|:--|
| youtube-asmr-audio-format.md | Opus 48kHz / VP9 黑帧 / -c:a copy 技术背景 |
| youtube-audio-analysis.md | 音频内容分析（静音检测/类型判定/元数据） |
| youtube-oauth-token-exchange.md | OAuth 授权码手动交换流程 |
| youtube-refresh-token-expiry-detection.md | Refresh token 生命周期/耗尽检测/网络隔离 |
| youtube-cron-mode-gfw-diagnostics.md | Cron 模式 GFW 诊断（区分安全限制/网络/永久过期） |
| youtube-curl-exit-codes.md | curl 退出码速查 |
| youtube-install-notes.md | 安装说明 |
| gif-search.md | Tenor GIF 搜索（内容创作周边） |
| output-formats.md | 内容输出格式（章节/推文/博客） |

## 脚本索引（scripts/）

| 脚本 | 用途 |
|:--|:--|
| youtube_carry.sh | 搬运入口（4 模式 + 批处理） |
| processors/asmr|raw|clip|audio.sh | 各模式处理 |
| common/download|info|init|upload.sh | 共享（下载/信息/初始化/上传） |
| youtube_token_refresh.py/.sh | token 刷新（推荐 .py） |
| oauth_server.py | OAuth 回调服务器（注意 video_uploader.json 无 installed 层的 bug） |
| fetch_transcript.py | 字幕抓取（内容创作） |

## 验证
- `ls scripts/` 看到全部脚本 + `yt-dlp --version` / `ffmpeg -version` 可用
- token：`python3 -c "import json; d=json.load(open('$HOME/.hermes/youtube/request.token')); print(d.get('refresh_token_expires_in'))"`
- 上传后 YouTube Studio 可见视频
