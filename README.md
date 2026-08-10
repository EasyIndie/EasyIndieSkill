# EasyIndieSkill

EasyIndie 内容自动化**统一 AI 技能包**（技能名 `easyindie`）——丢给任何 AI Agent（Claude Code / Hermes / OpenClaw / Cursor 等）即可处理内容创作与自动化工作。

> **多领域扩展设计**：YouTube 是第一个领域，后续选择性收录其它领域（音频、短视频、AI 音乐等）。每个领域 = references/ 前缀分组 + scripts/ 分组 + SKILL.md 路由表一行。

## 领域列表

| 领域 | 状态 | 能力 |
|:--|:--|:--|
| **youtube** | ✅ 已收录 | 搬运（下载→处理→上传 4 模式）、字幕转内容创作、OAuth token 管理 |
| audio / video / ai-music | 📋 规划中 | 按需选择性收录 |

## YouTube 领域能力

### 搬运工作流（下载 → 处理 → 上传）
- 4 种模式：`asmr`（黑帧 VP9+Opus）/ `raw`（原样）/ `clip`（截取）/ `audio`（MP3）
- 批处理：`--batch` 多链接 / `--file urls.txt`
- 磁盘 LRU 自动清理 + DISK_ALERT 告警
- 元数据提取 → 标题建议（按用户偏好模板，多方案供选）

### 内容创作
- 字幕抓取（youtube-transcript-api）→ 章节/摘要/推文串/博客/金句

### OAuth 与 Token 管理
- 6h 自动刷新 cron + 一键重授权脚本
- GFW 网络诊断（curl 退出码速查 / 代理方案）
- Refresh token 生命周期管理（≈2.7 天，连续失败需重新授权）

## 目录结构

```
easyindie/                     # 技能根（= 仓库根）
├── SKILL.md                   # 入口：领域路由表 + YouTube 领域完整内容
├── README.md                  # 本文件（仓库说明 + 扩展指南）
├── sync.sh                    # 一键同步（本地 skill → 本仓库，自动脱敏）
├── references/                # 知识体系（领域前缀分组）
│   ├── youtube-*.md           #   YouTube 领域知识（9 个）
│   ├── gif-search.md          #   Tenor GIF（内容周边）
│   └── output-formats.md      #   内容输出格式
├── scripts/                   # 工具（领域分组）
│   ├── youtube_carry.sh       #   搬运入口（asmr/raw/clip/audio + 批处理）
│   ├── processors/            #   各模式处理器（asmr.sh/raw.sh/clip.sh/audio.sh）
│   ├── common/                #   共享（download/info/init/upload）
│   ├── youtube_token_refresh.py/.sh  # token 刷新
│   ├── oauth_server.py        #   OAuth 回调
│   └── fetch_transcript.py    #   字幕抓取
└── templates/                 # 模板（可扩展）
```

## 使用方式（AI Agent）

```bash
# 加载技能
skill_view(name='easyindie')

# 搬运（默认 asmr）
bash scripts/youtube_carry.sh asmr <url>
# 批处理
bash scripts/youtube_carry.sh --batch clip -ss 5:00 url1 url2

# 内容创作
python3 scripts/fetch_transcript.py "<url>" --text-only --timestamps

# 上传（token 自动刷新）
source scripts/common/upload.sh && upload_video <file> "<title>" "<desc>"
```

## 扩展指南（新增领域）

新增领域（如 audio）三步：

1. **SKILL.md 路由表加一行**：
   ```markdown
   | **audio**（规划） | 音频处理/生成 | `references/audio-*.md` | `scripts/audio/` |
   ```
2. **knowledge 收录**：`references/audio-*.md`（前缀分组，与 youtube-* 并列）
3. **脚本收录**：`scripts/audio/` 子目录（或 `audio_*.sh` 前缀）

**命名规范**（保持可维护）：
- references 用 `领域-主题.md` 前缀分组（youtube-oauth.md、audio-format.md）
- scripts 用 `领域_动作.sh` 或 `领域/` 子目录
- 跨领域通用工具放顶层（scripts/common/）

## 同步与维护

```bash
./sync.sh "sync: youtube 领域整合"    # 一键同步到 GitHub + 自动脱敏
```

- 私有信息（账号邮箱、token 路径、用户特定偏好）已参数化/占位符化
- 标题偏好按用户区分（多用户场景），新用户偏好追加到 SKILL.md「标题偏好」段

## 兼容性

- 平台：macOS / Linux
- 技能格式：Claude Skills / OpenClaw / Hermes / Cursor 通用（frontmatter + markdown + scripts/）
- License: MIT
