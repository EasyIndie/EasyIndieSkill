# YouTube 发布卡片交互协议 + 操作手册

> 面向未来的 AI 会话：这是**发布环节**的操作手册。素材先经
> `references/youtube-file-channel.md`（直传通道）或链接通道加工成 `asset.json`，
> 再按本文档出卡片、等用户确认、然后才上传发布。
> **铁律：未收到用户明确确认前，绝不上传 / 不调用任何上传接口。**

## 1. 发布卡片模板

出卡片时**原样照抄**下面的结构（尖括号与数字、文字均为占位/示例，实际按 `asset.json` 填充）：

```
📹 #A1 发布候选 · <频道名>
────────────────────────
源：<源标题> ｜ 12:34 ｜ 源播放 12.3万 ｜ 3 天前
加工：asmr 黑帧 ✅ 已完成 ｜ 18.4MB ｜ Opus 48kHz
📱 Shorts：是（竖屏 9:16 · 89.6s ≤ 180s）　← 不合格时整行省略
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

字段说明（出卡片时必须给全）：
- `#A1`：本批候选编号，便于用户回复引用。
- `源`：源标题 / 时长 / 源播放量 / 发布时间（链接通道有；直传通道无则写「直传文件」）。
- `加工`：模式（`raw|asmr|clip|audio`）、是否黑帧、是否完成、输出体积、音频编码与采样率。
- `播放列表` / `标签`：默认值来自账号档案，标签后括号是数量。
- `封面`：`源抽帧 #N` 或 `文字封面`；`隐私` 来自账号 `doc_status` 推导的默认值。
- 标题候选：给 3~5 条，标出 ★推荐；用户回数字即选定发布。
- 描述：默认只给前 60 字预览，用户回「看描述」再看全文。

### Shorts（短视频）规则 · 2026-09-12 定案

| 项 | 规则 |
|:--|:--|
| **判定** | **方形或竖屏（宽高比 1:1 ~ 9:16，即 `width ≤ height`）+ 时长 ≤ 180 秒** → 平台自动归类为 Shorts。**API 无专门参数**，用标准 `videos.insert` 即可 |
| **数据来源** | `asset.json` 的 **`shorts`** 键（`eligible` / `aspect` / `width` / `height` / `duration` / `reason`），由 `youtube_ingest.py` 按**实际产物**探测 |
| **卡片标注** | `eligible=true` → 输出 `📱 Shorts：是（<aspect> · <时长>s ≤ 180s）`；`false` → **整行省略**（不写「否」，保持卡片干净） |
| **封面尺寸** | **按实际产物比例**推导：竖屏产物 → `1080×1920`；方形 → `1080×1080`；横屏产物 → `1080×720`（`imaging.detect_canvas`）。产物无视频流（如 audio 的 mp3）→ 回退源探测 → 都失败则 `1080×720` |
| **⚠️ 比例错配保护** | 若**源**与**产物**比例不同向（典型：竖屏源 + `asmr` → 横屏产物）→ 抽帧封面会错配，脚本自动**改用文字封面**并记 warning `源比例与产物比例不一致，封面已改用文字封面` |
| **asmr 模式** | ⚠️ 产物硬编码 `1920x1080` **横屏** → **必然不是 Shorts**。**已定案不加竖屏黑帧支持**（老板 #1②）：要发 Shorts 请用 `raw`/`clip`（保留原竖屏比例） |
| **封面显示** | ⚠️ Shorts 的自定义封面**不显示在 Shorts swipe feed**（feed 用自动帧），只在搜索结果/频道页/首页生效 —— **不是故障**，无需处理 |
| **注意** | `asmr`/`audio` 产物不是竖屏，长视频 >180s 也不是 Shorts；判定一律以**实际产物**为准（clip 截短后可能「变成」Shorts） |

## 2. 回复语法表

| 用户回复 | 含义 | 行为 |
| --- | --- | --- |
| 数字（如 `1`） | 选第 1 条标题 | 采用该标题，按默认隐私/默认播放列表/标签/封面发布 |
| `1 公开` | 选标题 + 指定隐私 | 隐私取 `public`（也接受 `公开`/`unlisted`/`不公开`/`private`/`私享`） |
| `1 12:00` | 选标题 + 定时 | 设置 `publishAt` 为今天/明天 12:00（本地时区），状态转 `scheduled` |
| `换` | 换一批标题 | 重新生成候选标题，卡片编号刷新，其他字段不变 |
| `改 标题=xxx` | 改标题 | 直接覆盖标题 |
| `改 描述=xxx` | 改描述 | 覆盖描述（多行可用换行续写，以空行或下一条指令结束） |
| `改 标签=a,b` | 改标签 | 覆盖标签（逗号分隔，自动去重、截断至平台上限） |
| `改 列表=xxx` | 改播放列表 | 覆盖播放列表（不存在则新建） |
| `改 封面=5` | 改封面 | 改用第 5 条标题对应的封面方案 / 或指定抽帧序号 |
| `改 定时=HH:MM` | 改定时 | 等价于设置 `publishAt` |
| `改 模式=asmr` | 改加工模式 | **重新加工同一素材 → 刷新卡片**（编号重排，其余字段保留）→ 重新等确认；`clip` 需补 `--clip-start/--clip-duration`（见 `youtube-file-channel.md` §3.5） |
| `看描述` | 查看全文描述 | 回显完整描述，不改状态 |
| `全A` | 批量确认 A 批全部 | 对 A 批所有候选按各自默认设置排队发布 |
| `停` | 取消/暂停 | 停止本次发布流程，删除候选（不发布） |

### 歧义处理规则（重要）

- 用户回复**不是**上表中的明确指令（自由文本）时，**不得擅自发布**。
- 必须先回显理解结果让用户确认：`理解为 X，回 y 确认`。
  - 例：用户回「深夜那个好听」，应回 → `理解为：选标题 1「…」发布，回 y 确认`。
- 用户回 `y` / `确认` / `是` 才执行；回其它则再澄清或走 `停`。
- 任何情况下，**默认隐私必须是推导值**；把 `live` 账号的 `public` 默认视为需二次确认的动作。

## 3. 状态机

```
queued → processing → awaiting_confirm → publishing → published
                                          ↘ scheduled（设置了 publishAt）
                                          ↘ failed（任一步出错）
```

| 状态 | 含义 | 允许的下一步 |
| --- | --- | --- |
| `queued` | 素材已入队，尚未加工/出卡 | 开始加工 → `processing` |
| `processing` | 加工/封面进行中 | 出卡成功 → `awaiting_confirm`；失败 → `failed` |
| `awaiting_confirm` | 卡片已发，等用户回复 | 收到确认 → `publishing`；`停` → 取消 |
| `publishing` | 正在上传 | 成功且无 publishAt → `published`；有 publishAt → `scheduled`；失败 → `failed` |
| `published` | 已发布 | 终态（记录台账） |
| `scheduled` | 已定时待发布 | 到点后转 `published`（由平台/定时任务完成） |
| `failed` | 任一步失败 | 修复后重新入队 `queued` |

状态变更都要落台账（见第 5 节），并保留 `asset.json` 以便重试。

## 4. 账号模型

- **账号档案位置**（默认）：`~/.hermes/youtube/accounts/<账号别名>.json`（或 `accounts.json` 内按别名分块）。
  档案只保存**非敏感元数据**（频道别名、默认播放列表、默认标签、隐私策略、限额等），
  **不写入任何真实令牌/密钥**；凭据由既有的 OAuth 机制管理。
- **`--account` 用法**：所有发布/账号相关命令都显式带 `--account <账号别名>`，
  避免默认账号误发。禁止把账号别名写死进本文档。
- **`doc_status`（test / live）**：
  - `test`：测试账号/测试项目 → **默认隐私 `unlisted`**（不出现在公开列表）。
  - `live`：正式账号 → **默认隐私 `public`**（发布前按第 2 节二次确认）。
  - 隐私命令行覆盖：`1 公开` / `--privacy`。
- **`daily_publish_cap`（风控）**：账号档案里的每日发布上限。达到上限后必须：
  - 停止批量发布并提示用户；
  - 除非用户明确要求且确认风险，才允许 `--force` 越过上限（**默认不使用**）。
- 批量（`全A` 等）发布前，先按 `daily_publish_cap` 预估剩余额度，超额部分排队到次日。

## 5. 台账

台账文件：`ledger.csv`（默认与素材同根，如 `~/.hermes/youtube/ledger.csv`）。
字段含义：

| 字段 | 含义 |
| --- | --- |
| `ts` | 记录时间（ISO8601） |
| `asset_id` | 素材/候选编号（对应 `asset.json`） |
| `account` | 账号别名 |
| `video_id` | 平台返回的视频 ID（未发布为空） |
| `title` | 发布的标题 |
| `privacy` | 实际隐私状态 |
| `playlist` | 播放列表 |
| `tags` | 标签（分号或逗号拼接） |
| `cover` | 封面路径或方案 |
| `mode` | 加工模式 |
| `status` | 状态机状态 |
| `publish_at` | 定时发布时间（无则空） |
| `error` | 失败真因（成功为空） |

常用查询命令：

```bash
# 最近记录
python3 scripts/youtube_ledger.py show --account <账号别名> --limit 20
# 按素材/视频/关键字查找
python3 scripts/youtube_ledger.py find <关键字>
# 汇总统计（按日/账号/状态）
python3 scripts/youtube_ledger.py summary --account <账号别名>
```

（以 `--help` 为准；不同版本子命令参数可能略有差异。）

## 6. 失败真因 → 处置对照表

| 现象 | 真因 | 处置 |
| --- | --- | --- |
| 上传返回配额错误（如 403 quotaExceeded / dailyLimitExceeded） | 单个 GCP 项目每天上传约 100 次的上限 | 等次日配额重置；把任务排队；必要时切换项目/账号 |
| 403 forbidden | 版权/权限问题（Content ID、频道权限不足、令牌 scope 不对） | 检查授权与内容合规；重新走 OAuth 授权；确认频道可上传 |
| 网络超时 / 连接重置 | 代理、网络不稳定、GFW | 配置/切换代理；重试并退避；参考网络诊断文档 |
| 文件或编码错误 | 容器/编码不受支持、文件损坏、体积超限 | 用 `youtube_ingest.py` 重新加工（如转 H.264/AAC、改 `--mode`）；确认文件完整 |
| 超过日更上限 | `daily_publish_cap` 触发 | 排队到次日；确需突破才由用户明确同意后 `--force` |
| 播放列表/标签未生效 | 目标播放列表不存在、标签超长被截断 | 先建播放列表；标签去重并截断；发布后回查核对 |

## 7. 端到端验收清单

1. **dry-run**：`python3 scripts/youtube_ingest.py --in <素材> --dry-run --json`，确认模式/时长/输出路径正确。
2. **真实 unlisted 上传**：用测试账号（`doc_status=test`，默认 `unlisted`）走完整卡片确认流程，
   发布一条 **unlisted** 视频。
3. **核对台账**：`python3 scripts/youtube_ledger.py find <asset_id or video_id>`，
   确认 `status=published`、`video_id`、`privacy=unlisted`、`ts` 等正确。
4. **核对设定是否生效**：在平台上确认 **指定播放列表 / 标签 / 封面** 均已按卡片设置生效。
5. **删除测试视频**：验收完成后删除该测试视频，并在台账补记/更新状态，避免污染统计。
6. **回归**：确认没有对生产账号 `live` 误发 `public`。

## 8. 实测坑（2026-09-12 一期真实验收，必读）

| # | 坑 | 真相 | 处置 |
|:--|:--|:--|:--|
| 1 | metaJSON 的 `categoryId` | youtubeuploader 的 Go `VideoMeta.CategoryId` 是 **string**；传数字 → `json: cannot unmarshal number ...` 直接 exit 5（未产生视频） | 我们的 `build_meta` 已统一输出字符串 `"24"`；`validate_go_meta_types()` 会拦截 |
| 2 | 文字封面 | **本机 ffmpeg 8.1.1 无 freetype/libass** → 没有 `drawtext`/`subtitles` 滤镜，文本渲染必挂 | 封面改用 **Pillow**（`lib/imaging.py`）；黑帧视频自动切文字封面 |
| 3 | `videos.list` 查不到 tags | 上传响应（`-metaJSONout`）里 tags 齐全，但 `videos.list` 可能返回 `tags: None` —— YouTube **索引延迟**（实测约 30s，改 public 后 30s 出现；改回 unlisted 仍可见） | **别误判为失败**：以 `-metaJSONout` / 上传响应为准；核验脚本可先等待或改 public 试探 |
| 4 | `playlistTitles` | 目标列表**不存在时会自动创建**（源码 `AddVideoToPlaylist`：按标题查找→找不到就 `Playlists.Insert`） | 档案里直接写列表名即可，无需手动建列表 |
| 5 | 频道统计 `videoCount` | 上传后立即查可能仍显示旧值（索引/统计延迟） | 以 `videos.list` + 播放列表成员为准 |
| 6 | 日更额度口径 | `failed` / `dry-run` 行**不占**日更额度 | `count_today` 只统计 `published`/`scheduled`；`include_failed=True` 可显式计入 |
| 7 | 自定义封面核验 | YouTube 会把 1080×720 封面转成 1280×720 | 无法靠 hash 比对；用「亮像素占比」判定（文字封面 ≈0.6–0.7%，纯黑抽帧 ≈0） |
| 8 | 台账 `duration` 列 | 上传层原本不写时长（ingest 探测结果与 upload 层解耦） | 已修：`youtube_upload.py` 未给 `--duration` 时**自动 ffprobe 探测**，写 1 位小数秒；探测失败只告警不阻断 |
| 9 | 封面画布按「源」推导 | 竖屏源 + `asmr`（产物固定横屏 1920x1080）→ 封面算出竖版 1080×1920，**与产物比例错配**，YouTube 的 16:9 封面槽会把文字裁掉 | 已修：画布改为**按实际产物推导**（产物无视频流才回退源）；源与产物比例不同向时**自动改文字封面** + warning。实测 asmr 竖屏源 → 封面 1080×720 ✅ |
| 10 | 横屏低分辨率源抽帧封面不放大 | 同向时抽帧保持原始宽高（如 640×360 → 封面 640×360）；YouTube 封面下限 640×360 可接受，但低分辨率源封面偏糊 | 已知限制（未改）：**建议源 ≥1080p**；若需强制规范到 1080 宽需另立需求 |
| 11 | **旋转矩阵（竖屏手机片）误导 Shorts 判定** | 手机竖拍片存的是 `1280x720` 码流 + `side_data rotation=-90`，**显示为 720×1280 竖屏**。`youtube_ingest.py` 的 `shorts` 探测只看码流宽高 → 错判「横屏 16:9 → 非 Shorts」；而**封面模块**（ffmpeg 抽帧自动旋转）拿到的是竖版 → 两者矛盾。实锤：2026-09-12 上传 `U0PzpfdJQes`，YouTube API `fileDetails.videoStreams` 回 `1280x720 rotation=clockwise` → **平台确实按竖屏处理，就是 Shorts** | 出卡时**人工看旋转矩阵**：`ffprobe -v error -show_entries stream_side_data=rotation -of json <f>`，`±90/270` → 显示宽高对调、按竖屏算 Shorts；根治需给 ingest 的 shorts 探测加旋转感知（待派单修复） |
| 12 | **账号品牌模板会污染非本类内容** | `account.yaml` 的 `default_playlists` / `tags_pool` / `title_template` / `description_template` **全是 ASMR 品牌**（含硬编码 `#asmr #助眠 #耳语`）。`--title` / `--description` 能覆盖模板，但 **tags 是「池 + 显式」合并**（`_norm_tags`）、**playlist 为空时回落账号默认** → 想发「非 ASMR」内容，光传 `--tags/--playlist` 去不掉 ASMR 标签、也进不了空列表（`--playlist ""` 会生成空标题列表，危险） | 临时做法（本次已用）：备份 `account.yaml` → 把 `default_playlists`/`tags_pool` 改 `[]` → 上传 → `\cp -f` 还原并用 `diff -q` 复核；**根治需加 `--no-playlist` / `--tags-pool none` 开关**（待派单修复） |

## 9. 可扩展点

### 多账号扩展 SOP（3 步）

1. 新建账号档案 `~/.hermes/youtube/accounts/<新别名>.json`：填 `doc_status`、默认播放列表、默认标签、
   `daily_publish_cap`（凭据走既有 OAuth，不写入档案）。
2. 用新别名完成一次 `--account <新别名>` 的 dry-run + unlisted 验收（第 7 节）。
3. 把该别名加入批量发布白名单/队列；卡片 `<频道名>` 与台账 `account` 字段按别名填写。

### 定时发布 `publishAt`

- 回复 `1 12:00` 或 `改 定时=HH:MM` 设置定时；平台侧使用 `publishAt`（RFC3339，含时区）。
- 到点后由平台发布；本地台账状态先记 `scheduled`，到点核对后更新为 `published`。
- 定时前仍可 `停` 取消；取消需同时清理平台侧的计划任务（若已创建）。

### 封面规则

- **黑帧视频（如 ASMR 黑屏源）必须使用源抽帧或文字封面**——绝不能用黑帧当作封面。
- 源抽帧：默认取 `min(3, 时长/10)` 秒处；可用 `--cover-frame` 指定，或在卡片里 `改 封面=5` 换方案。
- 文字封面：黑底白字、居中、最多 3 行，字体需支持中文；纯音频素材无画面，直接走文字封面。
- 发布前在平台上确认封面已生效（第 7 节第 4 步）。
