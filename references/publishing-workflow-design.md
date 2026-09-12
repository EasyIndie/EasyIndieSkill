# 飞书自媒体视频上传工作流 · 业务流程梳理 + 发布流程优化方案

> 提案版本 v1 · 2026-09-12 · 状态：**待老板拍板**
> 决策依据：#1 测试号 = Amazing Archive（后续扩展多账号）、#2 增强 upload.sh（播放列表/tags/缩略图/台账）、#3 不做无人值守上传（保持人工确认标题）、#4 旧 broadcast token 已删

---

## 0. 一页话摘要

| 维度 | 现状 | 目标 |
|:--|:--|:--|
| 交互 | 多轮问答（标题？隐私？）→ 老板打字等 | **一条卡片 = 一次发布决策**，默认值全预填，回 1 个数字即发 |
| 账号 | 单账号硬编码 | **账号档案制**（accounts/<name>.yaml），`-account` 切换 |
| 物料 | 标题必有、描述/tags/封面/播放列表全无 | **metaJSON 全量驱动**（标题+描述+tags+列表+封面+定时发布） |
| 可追溯 | 无台账 | **ledger.csv 上传台账**（含源链接/视频 ID/状态） |
| 加工 | 同步等 | **队列 + 进度回执**，长视频后台跑 |
| 复盘 | 无 | 台账 + （可选）Analytics 数据回采 |

**推荐路线：先落 A 方案（会话卡片协议，1–2 天见效）→ 再上 B（飞书卡片按钮，体验升级）→ C（多维表格看板）只在要规模化矩阵时启用。**

---

## 1. 现状诊断（2026-09-12 实测）

### 1.1 已有资产（可用，别重造）

| 资产 | 位置 | 实测状态 |
|:--|:--|:--|
| yt-dlp / ffmpeg / ffprobe / node | PATH | 2026.06.09 / 8.1.1 / 8.1.1 / v24.18.0 ✅ |
| youtubeuploader | `~/go/bin/` | 可用；支持 `-metaJSON`（含 publishAt / playlistIds / playlistTitles）、`-thumbnail`、`-tags`、`-playlistID`、`-categoryId`、`-language`、`-caption`、`-limitBetween` ✅ |
| 搬运入口 | `scripts/youtube_carry.sh` | 4 模式（asmr/raw/clip/audio）+ 批处理 + 磁盘 LRU ✅ |
| 上传函数 | `scripts/common/upload.sh` | 仅传 title/description/privacy（**未用上 playlist/tags/thumbnail/metaJSON**）❌ |
| OAuth | GCP `videouploader-500608`，scope `youtube.force-ssl` | 应用 **In production**，refresh token 长期有效 ✅ |
| Token cron | job `852818847356`，每 6h，`deliver=origin` | 今天 12:00 ok ✅ |
| 目标频道 | `Amazing Archive` `UCmUpPpgQhT_tqPr8wjxDojw` | 3 订阅 / **0 视频** / `longUploadsStatus=allowed` ✅（长视频可传） |

### 1.2 真痛点（按对老板时间的伤害排序）

| # | 痛点 | 具体表现 | 后果 |
|:--|:--|:--|:--|
| P1 | **确认流程碎** | 标题 5 选 1 一次、描述/隐私/列表各可能再问一次 | 一条视频 3–5 轮往返，老板时间被切碎 |
| P2 | **物料不成系统** | 描述/tags/封面/播放列表靠临场想，无账号模板 | SEO 与观看时长损失（播放列表是 ASMR 号最大留存杠杆） |
| P3 | **无台账** | 发过什么、发到哪、源是什么，全靠会话记忆 | 无法去重、无法复盘、换设备即失忆 |
| P4 | **单账号写死** | 加账号要改脚本 | 矩阵化被卡住 |
| P5 | **无风控节奏** | 想发就发，可能同日连发 | 搬运号被判 spam / reused content，账号权重受损 |
| P6 | **加工阻塞感** | 长视频编码十几分钟，老板不知道进度 | 体感卡顿，反复来问 |

---

## 2. 业务流程重建（资深自媒体视角）

> 自媒体发布不是「上传」一个动作，而是 **选源 → 收录 → 加工 → 文案 → 发布 → 复盘** 的闭环。
> 自动化边界原则：**机器做重复劳动，人只做审美决策（选源/选标题/拍板）。**

### 环节 1 · 选源（素材发现）

| 项 | 内容 |
|:--|:--|
| 现状 | 老板自己刷 YouTube → 丢链接；无源清单、无更新发现 |
| 痛点 | 全靠刷，错过更新；源质量参差（版权风险） |
| 目标形态 | `sources.yaml` 源频道清单（含授权类型/风格/时长偏好）→ **每日巡检新视频 → 推送候选池**（含时长/播放量/发布距今）→ 老板回编号选 |
| 自动化边界 | 机器：巡检+筛选+推送候选；人：选源拍板（审美+风险） |
| 阶段 | **二期**（一期先把发布链路做顺） |

### 环节 2 · 收录与加工

| 项 | 内容 |
|:--|:--|
| 现状 | `youtube_carry.sh <mode> <url>` 同步下载+编码；42min → 约 27min 编码 |
| 痛点 | 老板干等；批量时不知道第几个了 |
| 目标形态 | **作业队列**：收到链接即回「已入队 #A1（预计 8 分钟）」→ 后台跑 → 完成回「#A1 加工完成，进入文案确认」；失败自动重试 1 次并报真因 |
| 自动化边界 | 全自动（含磁盘 LRU、DISK_ALERT） |
| 阶段 | **一期**（用 background=true + notify_on_complete，无需新基建） |

### 环节 3 · 文案包装（发布物料）★ 价值最高

| 项 | 内容 |
|:--|:--|
| 现状 | 只给 5 个标题方案；描述/tags/封面/列表无 |
| 痛点 | 物料质量不稳定；每条重想一遍 |
| 目标形态 | **账号 persona 模板**：账号档案里存 标题公式 / 描述骨架 / tags 池 / 默认播放列表 / 默认隐私 / 分类 ID / 语言 → 我按模板 + 源视频特征（时长/音频类型/静音段/语言）生成**整包物料**，一次呈现 |
| 自动化边界 | 机器：生成候选（标题 5 个 + 描述 + tags + 封面候选）；人：拍板（选标题/改词） |
| 阶段 | **一期** |

**物料规格（ASMR 号参考）**

| 物料 | 生成规则 | 上限/注意 |
|:--|:--|:--|
| 标题 | 账号模板：`【ASMR】{简短标题}`（无时长前缀/分隔符），给 5 个 + 标★推荐 | ≤100 字符（中文有效约 30–40 字内） |
| 描述 | 骨架：① 一句场景钩子 ② 内容说明 ③ 关键词段 ④ Hashtags（3 个） | 前 2 行是搜索/推荐权重区，必须含关键词 |
| tags | tags 池（asmr/助眠/耳语/白噪音/放松…）+ 源视频 tag 提取 + 标题分词，去重取 10–15 个 | 单 tag ≤ 30 字符，总 ≤ 500 字符 |
| 封面 | ASMR 是**黑帧视频，抽帧必全黑**⚠️ → 从**源视频抽帧**或生成文字封面（1080×720 或 1280×720） | 需授权，`-thumbnail` 支持本地文件 |
| 播放列表 | 账号默认归档列表（如「ASMR 深夜」）；`-metaJSON` 的 `playlistTitles` 可按名字自动建列表 | ASMR 号**最大留存杠杆**，务必归档 |
| 分类/语言 | 默认 `categoryId=24`（Entertainment）+ 中文语言 | 可放账号档案 |

### 环节 4 · 确认与发布

| 项 | 内容 |
|:--|:--|
| 现状 | 多轮问答 → 上传 |
| 目标形态 | **一张发布卡片**（见第 3 节）→ 老板回 `1` → 上传 → 回执（视频链接 + 台账行 + Studio 链接） |
| 自动化边界 | 人只回 1 个数字；其余默认 |
| 阶段 | **一期** |

### 环节 5 · 复盘（台账 + 数据）

| 项 | 内容 |
|:--|:--|
| 现状 | 无 |
| 目标形态 | ① `ledger.csv` 台账（每次上传落一行）② （可选二期）上传后 48h/7d 回采播放量/CTR（YouTube Analytics API，需补 scope `yt-analytics.readonly`）→ 反哺标题模板迭代 |
| 自动化边界 | 全自动 |
| 阶段 | 台账**一期**；数据回采 **二期** |

---

## 3. 交互协议（核心 · A 方案）

### 3.1 设计三原则

1. **零输入可发布**：所有字段预填默认值 + ★推荐，老板回 1 个数字即完成。
2. **变更用短语法**：要改才追加，不强制逐项确认。
3. **一条素材一张卡片**：批量时编号，支持「全按推荐」。

### 3.2 发布卡片模板（飞书消息）

```
📹 #A1 发布候选 · Amazing Archive
────────────────────────
源：<源标题> ｜ 12:34 ｜ 源播放 12.3万 ｜ 3 天前
加工：asmr 黑帧 ✅ 已完成 ｜ 18.4MB ｜ Opus 48kHz
播放列表：ASMR 深夜 ｜ 标签：asmr, 助眠, 耳语, 白噪音 (12)
封面：源抽帧 #3 ｜ 隐私：unlisted（默认）
────────────────────────
标题（回数字即发）
1️⃣【ASMR】不良少女的深夜独白　★推荐
2️⃣【ASMR】雨夜耳语 · 无人知晓
3️⃣【ASMR】凌晨三点的低语
4️⃣【ASMR】耳机福利 · 沉浸耳语
5️⃣【ASMR】深夜独白 · 放松助眠
────────────────────────
描述：<前 60 字预览…>（回「看描述」看全文）
回复：1 · 1 公开 · 1 12:00 · 换 · 改 标题=xxx · 改 标签=a,b · 改 列表=xxx
      改 封面=5 · 看描述 · 停
```

### 3.3 回复语法表（老板只需要记「回数字」）

| 输入 | 含义 |
|:--|:--|
| `1` | 用方案 1 + 全部默认 → **直接上传** |
| `1 公开` / `1 私享` | 用方案 1，并改隐私 |
| `1 12:00` | 用方案 1 + **定时发布**当天 12:00（`publishAt`，先传为 private 定时公开） |
| `换` | 再给 5 个标题 |
| `改 标题=…` / `改 描述=…` / `改 标签=a,b,c` / `改 列表=…` / `改 封面=3` / `改 定时=明天20:00` | 单字段覆盖后**自动重发更新后的卡片**（不再问） |
| `看描述` | 输出完整描述全文 |
| `全A` / `1 2 3 全放` | 批量：把候选池按推荐一次发完（各自默认） |
| `停` / `取消` | 放弃当前候选（文件保留到 LRU 清理） |

**歧义规则**：只认「数字 / 数字+短参数 / 上述关键字」；其他自由文本我按意图理解并回显「理解为 X，回 y 确认」（防止误发）。

### 3.4 状态机

```
入队(queued) → 加工中(processing) → 待确认(awaiting_confirm)
   → 上传中(publishing) → 已发布(published)   ← 写台账
                        ↘ 失败(failed)       ← 报真因 + 建议（配额/版权/网络）
                                            ↘ 定时中(scheduled，publishAt)
```

### 3.5 上传成功回执（模板）

```
✅ #A1 已发布
链接：https://youtu.be/xxxxxxx
频道：Amazing Archive ｜ 隐私：unlisted
播放列表：ASMR 深夜 ✅ ｜ 封面 ✅ ｜ 标签 12 个 ✅
台账：ledger.csv 第 37 行
Studio：https://studio.youtube.com/video/xxxxxxx/edit
```

### 3.6 失败回执（真因导向）

| 真因 | 我给的处置 |
|:--|:--|
| `403 quotaExceeded` | 「今日 API 配额用尽（太平洋时间午夜重置）→ 排队到明天，或换账号/项目」 |
| `403 forbidden` / 版权 | 「可能是版权声明冲突 → 建议换源或加原创包装」 |
| GFW 超时（curl 28） | 「网络受限 → 走代理重试」 |
| 文件/编码错误 | 「源或编码问题 → 自动重试 1 次，仍失败则报错详情」 |

---

## 4. 多账号架构（#1 拍板：测试号 Amazing Archive，后续扩展）

### 4.1 目录结构（改造后）

```
~/.hermes/youtube/
├── accounts/
│   ├── amazing-archive/
│   │   ├── request.token          # 该账号 refresh token（自动刷新）
│   │   └── account.yaml           # 账号档案
│   └── <next-account>/…
├── video_uploader.json            # OAuth client（可多项目各一份 client.<project>.json）
├── ledger.csv                     # 全局上传台账（含账号列）
├── retired/                       # 已退役 token（如 request_broad.token.dead-20260912）
└── request.token → accounts/amazing-archive/request.token   # 兼容软链（旧脚本不炸）
```

### 4.2 账号档案字段（account.yaml）

```yaml
name: amazing-archive
display: Amazing Archive
channel_id: UCmUpPpgQhT_tqPr8wjxDojw
client_secrets: ~/.hermes/youtube/video_uploader.json   # 可指向不同 GCP 项目
default_privacy: unlisted          # 测试期建议 unlisted
default_language: zh
default_category: 24               # Entertainment
default_playlists: ["ASMR 深夜"]    # 名称（自动建）或 ID
tags_pool: [asmr, 助眠, 耳语, 白噪音, 放松, 深夜, 沉浸]
title_template: "【ASMR】{hook}"
description_template: |
  {hook}

  {summary}

  关键词：{keywords}
  #asmr #助眠 #耳语
doc_status: test                   # test=测试号（允许试错），live=正式运营号
daily_publish_cap: 3               # 单号日更上限（风控）
```

### 4.3 命令层

```bash
# 上传（upload v2）
upload_video <file> -account amazing-archive -meta <meta.json>
# 重授权（单账号，一次性授权后自动刷新）
python3 scripts/google_oauth_reauth.py -account <name>
# 刷新（cron 遍历所有账号）
python3 scripts/youtube_token_refresh.py --all-accounts
```

### 4.4 扩展新账号 SOP（3 步）

1. **Google 侧**：目标账号 Google 登录 → 用同一 OAuth client（或新项目 client）授权一次 → token 落 `accounts/<name>/request.token`
2. **档案**：复制模板 → 填 channel_id / 播放列表 / tags 池 / 标题模板 / 隐私
3. **验证**：`channels.list` 核对频道名 + 上传一条 5 秒测试片段（unlisted）→ 删

⚠️ **授权风控纪律（老板既定偏好）**：一次授权把所需 scope 全给（现在 `youtube.force-ssl` 已够上传+编辑+播放列表；若二期要数据回采，**这次一起把 `yt-analytics.readonly` 加上**，避免二次走网页授权触发风控）。

---

## 5. upload.sh v2 规格（#2 拍板）

### 5.1 核心改动：metaJSON 单一入口

`youtubeuploader -metaJSON` 支持：`title / description / tags / categoryId / privacyStatus / publishAt / playlistIds / playlistTitles / language / recordingDate / license / embeddable / publicStatsViewable / madeForKids`，且 **metaJSON 优先级高于命令行 flag**。

→ 于是 v2 设计：**我生成 `<work>/meta.json` → 一条命令上传全部物料**，upload.sh 只做「账号解析 + metaJSON 生成 + 调用 + 台账」。

```
upload_video(file, account, meta)
  ① 校验：文件/账号档案/token 存在
  ② 组 meta.json：账号默认 ⊕ 本次覆盖（标题/描述/tags/列表/隐私/定时/分类/语言）
  ③ 调 youtubeuploader -secrets -cache <账号 token> -filename -metaJSON -thumbnail -metaJSONout
  ④ 解析 videoId → 追加 ledger.csv → 输出回执 JSON
```

### 5.2 ledger.csv 台账字段

| 列 | 说明 |
|:--|:--|
| ts | 上传时间（本地时区） |
| account / channel | 账号名 / 频道名 |
| video_id / url | YouTube 视频 ID / 链接 |
| title | 最终标题 |
| source_url / source_title | 源链接/标题（去重用） |
| mode | asmr/raw/clip/audio |
| duration / size_mb | 时长 / 文件大小 |
| privacy / publish_at | 隐私状态 / 定时发布时间 |
| playlists / tags_count / thumbnail | 归档结果 |
| local_path / cleanup | 本地文件路径 / 是否已清理 |
| status / note | published/scheduled/failed + 备注 |
| operator | 触发人（老板 / cron / agent） |

### 5.3 其他增强

- `-thumbnail`：ASMR 黑帧抽帧必黑 → 默认从**源视频抽帧**；无源则生成文字封面（黑底白字，1080×720）
- `-tags`：账号 tags 池 ∪ 源 tag ∪ 标题分词 → 去重 → 截断上限
- 播放列表：`playlistTitles` 传名称（**上传时自动建列表**，省手动建）
- `-metaJSONout`：把 YouTube 返回的实际元数据落盘，便于对账（标题是否被改写/是否被限流）
- `-limitBetween`：可作「只在某时间段上传」的风控辅助
- `-caption`：可选（字幕/说明文件）
- 失败重试：网络类（curl 28）自动退避重试 1 次；配额/版权类**不重试**直接报真因

---

## 6. 平台约束与风控（资深从业者必须知道的硬天花板）

### 6.1 API 配额（2026-07 官方口径）

> 「启用 YouTube Data API 的项目默认配额 = **100 次 search.list + 100 次 videos.insert + 其他端点合计 10,000 units/天**，太平洋时间午夜重置。」
> 旧口径「videos.insert = 1600 units → 约 6 条/天」已被此新政策取代。

| 结论 | 影响 |
|:--|:--|
| **100 次上传/天/项目** | 单账号测试期完全够用；规模化上限是 100/天 |
| **配额按 GCP 项目算，不按账号** | ⚠️ **多账号共享同一 client 时是同一个 100/天池子**；要真正隔离 → 每个账号/矩阵组用**独立 GCP 项目**（各自一套 client_secrets） |
| 读操作吃 10,000 units | 源频道巡检（search.list 100 次上限 + playlistItems.list 更省 unit）→ 巡检脚本优先用 `playlistItems.list`（1 unit）而非 `search.list`（100 units） |
| 需要更高额度 | 提交 **Audit and Quota Extension Form**（免费，审核数周~数月，不保证通过） |

### 6.2 账号风险（搬运号生死线）

| 风险 | 说明 | 缓解 |
|:--|:--|:--|
| **版权罢工**（3 strikes 废号） | 整段搬运他人 ASMR 音频易被 Content ID 命中 | ① 优先 CC-BY/授权源；② 二次创作（重混/加环境层/改结构）；③ 建立「安全源白名单」；④ 测试号先跑（`doc_status: test`） |
| **Reused Content 政策** | 纯搬运难获获利资格（YPP 审核） | 定位为流量/引流或做「精选 + 原创包装（封面/文案/编排）」；不要指望纯搬运开通获利 |
| **Spam / 连发** | 同日大量上传同类内容触发降权 | `daily_publish_cap`（建议 ≤3/号/天）+ **错峰 publishAt**（定时发布拉开发布时间） |
| 长视频 | 未验证账号 >15min 视频被拒 | 本号 `longUploadsStatus=allowed` ✅ 已验证 |
| 疑似机器人操作 | 高频 API 写操作 | 控制节奏、`-ratelimit`/`-limitBetween` 可选 |

---

## 7. 方案对比与推荐路线

| # | 方案 | 交互形态 | 改动量 | 优点 | 缺点 | 建议 |
|:--|:--|:--|:--:|:--|:--|:--|
| **A** | **会话卡片协议**（文本卡片 + 短语法） | 发链接 → 收卡片 → 回 `1` | 小 | 立刻可用、零新基建、稳定、飞书原生渲染好 | 是文本消息，非真按钮 | ✅ **一期落地** |
| **B** | **飞书交互卡片按钮** | 卡片上点 `[✅发布]`/`[换标题]` | 中 | 体验最佳、一键完成、可显示状态 | 需实测按钮回调；卡片文本容量有限，长描述仍需文字补充 | ✅ **二期（先发测试卡验证）** |
| **C** | **多维表格（Bitable）发布看板** | 表格里审核文案 + 勾选发布 | 大 | 批量/多账号矩阵/可协作最强，天然台账 | 基建重（Bitable API+权限+双向同步），单人日常过重 | ⏳ **规模化时再上** |
| D | 全自动无人值守上传 | 无交互 | 小 | 最省事 | 老板已否决（#3）；且风控上不明智 | ❌ 不做 |

**为什么推荐 A 先落**：它把 P1–P6 里 5 个痛点一次解决，改动只在「脚本增强 + 技能话术协议」，不引入任何新服务，失败面最小；而 B 的卡片按钮**技术上已验证可行**（Hermes 飞书适配器会把非 approval 卡片按钮路由成合成命令进会话，见附录 A），但值得先跑通 A 的物料/台账基建再上 B，避免一次性改太多。

**分期路线**

| 期 | 内容 | 交付物 |
|:--|:--|:--|
| **一期** | A 方案 + upload.sh v2（metaJSON/播放列表/tags/封面/台账）+ 多账号档案 + 作业队列进度回执 | 脚本 PR + 技能更新 + 一条真实测试上传（unlisted）验证 |
| **二期** | B 飞书卡片按钮（先测试卡验证回调）+ 源频道巡检候选池 + Analytics 数据回采 | 卡片模板 + sources.yaml + 数据报表 |
| **三期** | （按需）C 多维表格看板 / 多 GCP 项目矩阵 / 配额提升申请 | 按老板矩阵规划定 |

---

## 8. 任务清单与待决策项

**执行序（一期，批准后）**

1. `upload.sh` v2 + `accounts/` 迁移 + `ledger.csv`（含向后兼容软链）
2. `youtube_token_refresh.py --all-accounts`（cron 兼容单账号现状）
3. 账号档案 `accounts/amazing-archive/account.yaml`（含播放列表/tags 池/标题模板）
4. 技能更新：发布卡片话术协议 + 台账规范 + 多账号 SOP（easyindie 技能 references）
5. **端到端验收**：一条真实素材走完「卡片 → 回 1 → 上传 → 回执 → 台账」，unlisted，事后删除
6. 编程按既定工作流交**本地编码智能体（首选 `pi`，claude 回退）**，Hermes 做编排/验收/推送

**待老板拍板项**

| # | 决策项 | 我的建议 |
|:--|:--|:--|
| **#1** | 一期范围是否就按上面 6 步做 | 建议：是（约 1 个工作日，含验收） |
| **#2** | 默认隐私：测试期 `unlisted`，正式运营号改 `public`？ | 建议：测试号 unlisted，正式号 public |
| **#3** | 标题方案数量：保持 5 个（含★推荐）还是压到 3 个更清爽？ | 建议：5 个（搬运选题容错高），卡片上★标推荐 |
| **#4** | 是否要「定时发布 publishAt」错峰（如 `1 12:00`） | 建议：要（免费风控杠杆） |
| **#5** | 单号日更上限 `daily_publish_cap` 设几？ | 建议：3（搬运号安全区） |
| **#6** | 二期是否加 `yt-analytics.readonly`（数据回采）—— **若要，建议下次授权一次性加上** | 建议：加（避免二次授权触发风控） |
| **#7** | 要不要现在做 B 卡片按钮的「测试卡验证」（我发一张卡，老板点一下，确认回调链路） | 建议：一期完成后做 |
| **#8** | 源频道清单（环节 1）是否已有目标源？ | 建议：老板给 3–5 个源频道，二期做巡检候选池 |

---

## 附录 A · 飞书卡片按钮技术结论（实测代码依据）

- Hermes 飞书适配器 `plugins/platforms/feishu/adapter.py`：
  - 注释明确：「Interactive card button-click events routed as synthetic COMMAND events」
  - `_on_card_action_trigger` → 非 approval 的按钮 → `_handle_card_action_event` → 构造 `text = "/card button {json}"` 的 **COMMAND 事件**进入当前会话（含点击者 open_id / chat_id）
- **推论**：按钮 `value` 里带 `{"job":"A1","choice":"1"}`，点击后我就能收到并据此执行发布 → **B 方案可行，无需自建回调服务**
- 待验证：`/card ...` 作为 COMMAND 是否会被 Hermes 当斜杠命令拦截（需一次真实点击测试，即拍板项 #7）
- 发送卡片路径：`lark-cli api POST /open-apis/im/v1/messages`（`msg_type=interactive` + card JSON）；文本卡片的 Markdown 走现有 `lark-cli im +messages-send --markdown`

## 附录 B · 现有资产与命令速查

```bash
# 搬运（4 模式）
bash scripts/youtube_carry.sh asmr "<url>"          # 默认；黑帧 VP9 + Opus(copy)
bash scripts/youtube_carry.sh --batch asmr url1 url2
# 上传（现状）
source scripts/common/upload.sh && upload_video <file> "<title>" "<desc>" [privacy]
# 上传（v2 目标）
upload_video <file> -account amazing-archive -meta <meta.json>
# token
python3 scripts/youtube_token_refresh.py            # 单账号
python3 scripts/youtube_token_refresh.py --all-accounts
python3 scripts/google_oauth_reauth.py -account <name>
# 台账
column -s, -t ~/.hermes/youtube/ledger.csv | tail -20
```

## 附录 C · 本次已执行

| 项 | 状态 |
|:--|:--|
| #4 旧 broadcast token | ✅ 已移出活跃目录 → `~/.hermes/youtube/retired/request_broad.token.dead-20260912`（含 evidence 副本），活跃目录仅剩 `request.token` |
| 受影响文档 | `references/youtube-cron-mode-gfw-diagnostics.md` 第 8 节仍提 backup token → 一期一并更新为多账号模型 |
