# 飞书直传文件通道（通道 2）说明

> 面向未来的 AI 会话：老板把视频/音频文件**直接发到飞书**时，按本文档处理。
> 本通道只做「落盘 → 探针 → 加工 → 封面 → 出素材档案」，**不执行任何上传**；
> 上传与发布由发布流程（见 `references/youtube-publish-workflow.md`）在用户确认后进行。

## 1. 通道定位

工作流有两条素材通道：

| 通道 | 入口 | 素材获取方式 |
| --- | --- | --- |
| 通道 1（链接通道） | 老板发 YouTube 链接 | `scripts/youtube_carry.sh <mode> <url>` 下载后加工 |
| 通道 2（本通道，直传通道） | 老板直接在飞书发**视频/音频文件** | Hermes 飞书适配器已把附件自动下载到本机，得到一个本地路径 → 用 `scripts/youtube_ingest.py` 处理 |

通道 2 的关键前提（已确认，无需再排查）：Hermes 飞书适配器收到 文件/视频/音频 消息附件后，
会**自动下载到本机缓存**，并把「本地路径 + media_type」交给 agent；消息文本中会显示
`[Attachment: 文件名]`。因此本通道的输入就是**一个本地文件路径**（或一个目录）。

## 2. 触发识别

收到消息后，按以下规则判断走哪条通道：

- 消息里出现 `[Attachment: xxx]`，且 agent 上下文/工具结果里给出了对应的**本地文件路径** → 走本通道。
  - 常见路径形态：Hermes 缓存目录下的下载文件（视频多为 `.mp4`）。
- 消息里同时出现 YouTube 链接 → 优先走**链接通道**（通道 1），链接可溯源、信息更全。
- 只有链接没有附件 → 通道 1。
- 只有附件没有链接 → 通道 2。
- 附件消息**文本很短或为空**时，仍以附件为准；不要因为「没有标题」而跳过，标题可用文件名净化得到。

## 3. 处理 SOP（编号步骤）

设 skill 目录为 `<skill dir>`（通常 `~/.hermes/skills/media/easyindie`）。

1. **确认真实本地路径**：从 Hermes 给的文件路径出发，先确认文件存在且非空。
   ```bash
   ls -la "<本地文件路径>"
   ```
   若路径是目录（一次收到多个附件），可对整个目录处理。

2. **磁盘预检 + 探针（dry-run）**：先只探针不加工，确认模式与时长，避免误加工。
   ```bash
   cd <skill dir>
   python3 scripts/youtube_ingest.py --in "<本地文件路径>" --mode auto --dry-run --json
   ```
   默认要求至少 500MB 可用空间（`--min-free-mb` 可调）；空间不足会以退出码 6 退出并提示清理。

3. **按需加工**：确认无误后正式加工。`--mode auto` 会自动判定：有视频流 → `raw`，纯音频 → `audio`。
   ```bash
   python3 scripts/youtube_ingest.py --in "<本地文件路径>" --mode auto --json
   ```
   指定模式（`raw|asmr|clip|audio`）时：
   ```bash
   # ASMR：黑帧 VP9 + 音频
   python3 scripts/youtube_ingest.py --in "<本地文件路径>" --mode asmr --json
   # 截取片段（-ss/-to/-t 用法与 clip.sh 一致）
   python3 scripts/youtube_ingest.py --in "<本地文件路径>" --mode clip --clip-start 00:01:00 --clip-duration 60 --json
   # 只要音频（192k MP3）
   python3 scripts/youtube_ingest.py --in "<本地文件路径>" --mode audio --json
   ```

4. **一次处理多个附件**：把 `--in` 指向目录即可，目录内视频/音频会按文件名排序逐个处理，
   `--json` 输出为数组。
   ```bash
   python3 scripts/youtube_ingest.py --in "<附件所在目录>" --mode auto --json
   ```

5. **查看产物**：每个素材落在 `<out-dir>/<asset_id>/`（默认 `~/.hermes/youtube/inbox/<asset_id>/`）：
   - `source.<ext>`：入站文件副本（**不改动、不删除**原缓存文件）
   - `output.*`：加工结果（`raw`/`clip` → `output.mp4`，`asmr` → `output.webm`，`audio` → `output.mp3`）
   - `cover.jpg`：封面（源抽帧；源接近全黑或纯音频时自动改黑底文字封面）
     - 文字封面由 **Pillow** 绘制（本机 ffmpeg 8.1.1 构建不含 freetype，`drawtext`/`subtitles` 滤镜不可用，故不用 ffmpeg 渲染文字）；
     - 换行按像素宽度测量，最多 3 行、超出加省略号，字号自适应 64→48→40（1080x720）；
     - 中文字体回退顺序 PingFang → Songti → Arial Unicode → Arial，全部缺失则报错；可用 `EASYINDIE_FONT` 指定；
     - 极端情况下（Pillow 缺失）退化为纯黑封面，并在 `asset.json` 的 `warnings` 中记录。
   - `asset.json`：素材档案（UTF-8）

6. **自定义项**（可选）：
   - `--name <slug>` 覆盖素材 slug（默认由文件名净化：小写、非字母数字转 `-`、截断 40 字符）；
   - `--source-url <url>` / `--source-title <标题>` 写入档案，供发布卡片展示溯源；
   - `--cover-frame <秒>` 指定抽帧时间（默认 `min(3, 时长/10)`）；
   - `--text-cover` 强制文字封面；`--cover-text "<文字>"` 指定封面文字。

7. **交给发布流程**：把 `asset.json` 交给发布卡片流程（见
   `references/youtube-publish-workflow.md`），由 Hermes 出卡片、用户确认后再上传发布。
   **本步骤之前不得调用任何上传接口。**

## 3.5 零指令协议（文件消息无 caption 场景）

> **背景**：飞书客户端发送**文件消息**时**无法附带文字说明**（文件与文字只能是两条独立消息）。
> **老板决策（2026-09-12，编号回复 #1② #2③ #3）**：
>
> | 项 | 决策 | 含义 |
> |:--|:--|:--|
> | 自动模式 | **#1 ② 不加** | ❌ 不把「黑屏视频自动走 asmr」加进 `auto`；`auto` 保持「有视频流 → `raw`，纯音频 → `audio`」 |
> | 文件名前缀 | **#2 ③ 不用** | ❌ 不启用 `asmr-`/`raw-` 前缀约定 —— **一律纯靠发布卡片改** |
> | 默认隐私 | **#3** | ✅ 沿用账号档案值（测试号 `amazing-archive` = `unlisted`） |

**协议核心：说明后置到卡片，零前置文字依赖。** 无 caption 唯一的影响是「加工模式无法提前指定」（加工在出卡之前），其余字段全部在卡片上后置确认。

1. 收到附件（文本为空/极短**照常处理**，不得因「没说明」跳过）→ 直接进 §3 SOP，模式用默认 `auto`（→ `raw` / `audio`）。
2. 出发布卡片时**必须把「加工」行的模式写出来**，让用户知道当前按哪种模式加工。
3. 用户回 `改 模式=asmr` → 用**同一素材重新加工**（`youtube_ingest.py --mode asmr --name <原 slug>`，覆盖原 asset 目录）→ **刷新卡片**（编号重排，其余字段保留）→ 重新等确认。
   同理 `改 模式=clip` 需一并给出 `--clip-start/--clip-duration`（卡片里追问）。
4. 标题/描述/标签/列表/封面/隐私 → 全部卡片后置确认，不受无文字影响。
5. **多附件**：一次发多个文件 → 全部落盘 → 出**批量卡片**（`#A1/#A2/...`）→ 支持 `全A` 一键全发（先按 `daily_publish_cap` 预估额度）。
6. **附件没落盘**（>100MB 静默失败 / 空消息）→ **不要让老板重发**，先跑 §6.2 兜底：
   `python3 scripts/feishu_fetch_attachment.py --minutes 30 --with-cover`。
7. 标题草稿来源：文件名净化（§3 第 6 点 `--name` 规则），再在卡片上给 5 条候选。

## 4. 支持格式与建议

- 视频：`mp4` / `mov` / `mkv` / `webm` / `avi`（以及 `m4v/flv/wmv/ts`）。
  - 建议优先发 **mp4（H.264 + AAC）**，兼容性最好、`raw` 模式可直接复制、无需转码。
  - 非 mp4 视频走 `raw` 时会先 `-c copy` remux 到 mp4，失败再回退 H.264/AAC 转码（会耗时）。
- 音频：`mp3` / `m4a` / `wav` / `flac` / `ogg`（以及 `aac/opus/wma`）。
  - `wav`/`flac` 体积大，长音频建议先自行压成 `m4a`/`mp3` 再发，或直接用 `--mode audio` 输出 192k MP3。

### 4.1 YouTube Shorts（短视频）支持 · 2026-09-12 定案

| 项 | 规则 |
|:--|:--|
| **判定** | **方形或竖屏（`width ≤ height`，1:1 ~ 9:16）+ 时长 ≤ 180 秒** → YouTube 自动归类为 Shorts（**API 无专门参数**） |
| **哪些模式能出 Shorts** | `raw` ✅（保留原比例）、`clip` ✅（不缩放，截到 ≤180s）；`asmr` ❌（产物固定 `1920x1080` 横屏）、`audio` ❌（纯音频） |
| **识别落点** | `asset.json` 新增 **`shorts`** 键：`{eligible, aspect, width, height, duration, reason}`，由 `youtube_ingest.py` 按**实际产物**探测（`--dry-run` 时探源文件）；`human_summary` 对合格素材加 `📱 SHORTS` 标记 |
| **封面尺寸** | **按实际产物比例**推导：竖屏产物 → `1080×1920`；方形 → `1080×1080`；横屏产物 → `1080×720`；产物无视频流 → 回退源 → 默认 `1080×720`。源与产物比例不同向时**自动改文字封面**（warning 提示） |
| **已定案不加** | ⚠️ **不为 asmr 模式加竖屏 9:16 黑帧支持**（老板 #1②）—— 要竖版 ASMR Shorts 需另立需求 |
| **封面显示** | ⚠️ Shorts 自定义封面**不显示在 Shorts swipe feed**（feed 用自动帧），只在搜索/频道页/首页生效 —— 平台行为，非故障 |

## 5. 飞书消息附件大小上限（已实测，2026-09-12）

### 5.1 机器人上传（bot → 用户，出站）＝ **30 MB 硬上限**

用递增体积真实刷新二分测试（bot 身份，同一 DM）：

| 消息类型 | 30 MB | 31 MB | 35 MB | 40/45 MB | 50 MB | 100 MB |
|:--|:--:|:--:|:--:|:--:|:--:|:--:|
| 文件消息（`--file`） | ✅ 体积过（仅类型校验拦假文件） | ❌ | ❌ | ❌ | ❌ | ❌ |
| 视频消息（`--video`+`--video-cover`） | ✅ 发送成功 | — | — | ❌ | — | — |

- 失败错误码统一为 **234006 `The file size exceed the max value.`**
- **结论：文件消息与视频消息共用同一上传限制（30 MB）——「改发文件消息」绕不过去**（2026-09-12 老板提议，已实测否决）
- 假文件（全零 `.mp4`）会先在体积之后被**类型校验**拦下（错误码 **230055** `The type of file upload does not match...`）→ 可作为「体积已通过」的判定信号

### 5.2 机器人下载附件（入站，老板发给我）＝ **>100 MB 必然下载失败**（2026-09-12 实锤）

同一批文件、同一个 bot 身份，两条下载实现对比：

| 下载实现 | 0.33 MB | 30 MB | **106 MB** |
|:--|:--:|:--:|:--:|
| Hermes 用的 `lark_oapi` SDK（`message_resource.get` 一次性下载） | ✅ | ✅ | ❌ **234037 `Downloaded file size exceeds limit.`** |
| `lark-cli im +messages-resources-download --type file`（同 bot 身份） | ✅ | ✅ | ✅ **成功（111,556,409 字节）** |

**推论与现象**：

- 老板用客户端发 **9.1 GB** 都没问题（客户端侧几乎无小上限）——但**机器人侧下载 >100 MB 会被平台拒绝**：文件「看得见、拿不到」。
- Hermes 适配器下载失败**只记 DEBUG 日志**、不产出任何提示 → 表现为**「消息是空的、附件凭空消失」**（日志：`Inbound dm message received: type=document text='' media=0`）。**这是"附件丢失"的头号真因**（不是消息类型问题）。
- 即使下载成功，Hermes 也是**整块读入内存**（`_read_binary_response` → `bytes(file_obj.read())`，无流式、无上限保护）→ 百 MB 级尚可，多 GB 会拖垮 16 GB 机器。

### 5.2.1 素材大小 → 通道选择（工作流约定）

| 素材大小 | 推荐通道 | 理由 |
|:--|:--|:--|
| ≤ 100 MB | 飞书直传（老板直接发） | Hermes 可自动下载 |
| **> 100 MB** | **① agent 用 lark-cli 手动取（SOP 见 6.2）② 或 SMB「下载」共享 / 本机目录** | SDK 下载必失败；lark-cli 实测 106 MB 成功 |
| 多 GB | SMB / 本机目录（优先） | 省飞书上传时间，零内存风险 |
| 有链接 | 链接通道（yt-dlp） | 不占飞书带宽 |

### 5.3 lark-cli 媒体参数路径坑（2026-09-12 实测）

`--file` / `--video` / `--video-cover` / `--image` 只接受 **cwd 相对路径**、`file_xxx` key 或 URL；
**传绝对路径会直接 exit 2（CLI 用法错误，不是 API 拒绝）** → 先把文件 `\cp -f` 到当前目录，再用 `./name` 引用。

### 超限替代通道（附件发不出来时）

1. **本机目录投递**：把文件放到本机 `~/Downloads` 或 `~/.hermes/youtube/inbox`，
   再让 agent 用该路径跑 `youtube_ingest.py`（等价于通道 2 的输入）。
2. **macOS SMB 共享**：开启「文件共享」，共享名 **「下载」**；老板从电脑/手机上传到该共享目录后，
   agent 按上面的「本机目录投递」处理。
3. 若文件本身是网络可访问的链接，可改走**链接通道**（通道 1）。

## 6. ⚠️ 视频消息 vs 文件消息（2026-09-12 实测 + 一处误判更正）

飞书客户端发视频会走**两种消息类型**：

| 消息类型 | 飞书行为 | 我们拿到的 | 处置 |
|:--|:--|:--|:--|
| **视频消息**（`msg_type=media`） | 可能转码，**也可能原样保留**（实测本例未转码） | 取决于平台处理 | 下载后**用 A/B 比对法**判定（6.1），**不要凭 metadata 猜** |
| **文件消息**（`msg_type=file`） | 原文件直传（字节级一致） | 原片 | 直接用 ✅ |

**大视频客户端会自动转成文件消息发送**（老板实测），大文件反而更容易拿到原片。

### 6.1 「是否原片」的正确判定：A/B 比对（❌ 不要凭 metadata 猜）

⚠️ **更正（2026-09-12，我此前误判过并让老板白白重发一次）**：曾用「`encoder=Lavf*` + `major_brand=isom` + 无 Apple 元数据 + `description=miaojian`」四要素判定视频"被飞书转码"，**这是错的**——这些特征来自**源文件本身**：该文件是**秒剪（MiaoJian）导出**产物（文件名 `MJ_` 前缀印证），秒剪导出天然就是 FFmpeg 编码 + isom 容器 + `miaojian` 签名。**metadata 无法区分「应用导出」与「平台转码」。**

**可靠方法 = 同一文件分别用「视频消息」与「文件消息」各发一次，下载后比对 MD5/大小：**

```bash
lark-cli im +messages-resources-download --message-id <media_msg> --file-key <fk1> --type file --output a.MOV
lark-cli im +messages-resources-download --message-id <file_msg>  --file-key <fk2> --type file --output b.MOV
md5 a.MOV b.MOV        # 一致 = 视频消息未转码，即原片
```

**2026-09-12 实况**：老板先发视频消息、再发文件消息 → 两者 **MD5 完全一致**（`76caa6a6…`，111,556,409 字节）→ **飞书未转码，视频消息拿到的就是原片**。

**次优方法（没有文件消息对照时）**：向老板索要源文件大小/分辨率，与我们下载到的 `ffprobe` 规格（size/bitrate/分辨率/时长）**逐项对照**；确有差异才提示「请改发文件消息重发」。

### 6.2 「附件收不到」的真因与兜底 SOP

真因**不是**消息类型，而是 **>100 MB 下载被平台拒绝（234037）+ 失败静默**（详见 5.2）。**空消息 = 附件下载失败的典型表现**。

**兜底 SOP（已实测跑通，2026-09-12）**：

**首选：一条命令自动兜底**（推荐，收到空消息就先跑它）
```bash
cd <skill dir> && python3 scripts/feishu_fetch_attachment.py --minutes 30 --with-cover
# 默认 chat_id 取自 ~/.hermes/youtube/feishu.yaml 的 default_chat_id（真实值不入公开仓库）
# 输出：✅ 下载 xxx（106.4MB）→ 路径 ; 汇总: scanned=50 found=2 downloaded=2 skipped=0 failed=0
# 幂等：已抓过的消息再次运行会 skipped（状态文件 ~/.hermes/youtube/feishu_fetched.json）
```
实测：2 条附件（含 106MB 视频）+ 1 张封面，**23 秒**全部落盘到 `~/.hermes/youtube/inbox/from-feishu/<YYYYMMDD>/`。

**手动兜底（脚本不可用时）**：
```bash
# 1) 拿到 message_id 与 file_key（content 形如 <file key="file_v3_..." name="x.MOV"/>）
lark-cli im +chat-messages-list --chat-id <chat_id> --order desc --page-size 30 --format json
# 2) lark-cli 下载（⚠️ 一律用 --type file；type=video/media 不存在 → 234001）
cd <目录> && lark-cli im +messages-resources-download \
  --message-id om_xxx --file-key file_v3_xxx --type file --output boss_video.MOV
# 3) 原片判定（6.1）→ 再进 youtube_ingest.py 走流水线
```

- 视频消息的**封面图**也能下载（`cover_image_key`，`--type image`），可作缩略图素材（脚本 `--with-cover` 已内置）。
- 上游改进建议（可选）：① 下载失败改记 WARNING 并在消息里标注「附件下载失败：超过 100MB」而不是静默空消息；② 改用分块/Range 下载；③ 加大小上限 + 流式落盘。本地核心保持跟踪上游、勿分叉。

### 6.1 视频消息里的「非原片」判定（四要素，命中任一即为转码）

| # | 检查 | 原片（iPhone/相机） | 飞书转码版 |
|:--|:--|:--|:--|
| ① | `format.tags.encoder` | 硬件编码器标识（如 `com.apple.*`/机型名） | **`Lavf58.20.100`**（FFmpeg 二次编码） |
| ② | `format.tags.major_brand` | **`qt`**（QuickTime） | **`isom`**（`isomiso2avc1mp41`） |
| ③ | Apple/QuickTime 元数据 | 有 `com.apple.quicktime.model`/`creationdate`/`location` | **全部被剥（0 条）** |
| ④ | `format.tags.description` | 无 | **`miaojian`**（秒剪 / 飞书系转码器签名） |

一条命令：
```bash
ffprobe -v error -show_format -of json <file> | grep -E "encoder|major_brand|description|apple"
```
2026-09-12 实测样本：老板发的 `MJ_1771310428.MOV`（90s）→ 四项全中（106 MB / 1920×1080 / 9.96 Mbps）→ **判定为转码版，已提示老板改发文件消息**。

### 6.2 ⚠️ Hermes 侧已知问题：视频消息**收不到**（需手动下载兜底）

日志实锤（2026-09-12 15:25:28）：

```
[Feishu] Received raw message type=media message_id=om_...
[Feishu] Inbound dm message received: ... type=document ... text='' media=0
```

→ Hermes 飞书适配器对 `msg_type=media` **没有产出 media_ref / 没有下载**，消息以**空文本**进入会话（还会触发「empty non-content message」自愈告警）。**text 通道也拿不到内容**，等于消息丢失。

**兜底 SOP（当前唯一可行路径）**：
```bash
# 1) 找消息与 file_key（content 形如 <video key="file_v3_..." name="x.MOV" duration="90s"/>）
lark-cli im +chat-messages-list --chat-id <chat_id> --order desc --page-size 30 --format json
# 2) 用 type=file 下载（⚠️ 视频消息必须用 type=file；type=video 不存在）
cd <某个目录> && lark-cli im +messages-resources-download \
  --message-id om_xxx --file-key file_v3_xxx --type file --output boss_video.MOV
# 3) 转码判定（6.1 四要素）→ 再决定是否要求重发
```
- 备用：视频消息的**封面图**也能下载（`cover_image_key`，`--type image`），可作缩略图素材。
- 建议：向上游报 issue「Feishu adapter drops msg_type=media (empty text, media=0)」。本地核心保持跟踪上游、勿分叉。

## 7. 常见失败与处置

| 现象 | 可能真因 | 处置 |
| --- | --- | --- |
| 飞书附件未落盘 / 无本地路径 | 消息里没有 `[Attachment: ...]`；或附件超限、下载失败 | 让老板重发；改用「本机目录 / SMB 共享」通道；确认适配器缓存目录是否有对应文件 |
| 落盘文件为空（0 字节） | 下载中断、磁盘满 | 检查磁盘；让老板重发；确认后删除空文件 |
| 探针失败（退出码 4） | 文件损坏或非媒体（如把压缩包当视频发） | 让老板确认原始文件可播放后重发；非媒体文件不进入本通道 |
| 加工失败（退出码 5） | 编码异常、容器/流不受支持、ffmpeg 报错 | 看 stderr 尾部（脚本会带出）；尝试改 `--mode`（如 `audio`）或先转码为 mp4 再处理 |
| 磁盘不足（退出码 6） | 可用空间低于 `--min-free-mb` | 先清理 `~/.hermes/youtube/inbox` 下旧素材或 `~/Downloads`，再重跑 |
| 封面是文字而非抽帧 | 源接近全黑（ASMR）或纯音频，属预期 | 无需处理；如需指定文字用 `--cover-text`，如需真实画面用非黑帧源 |

## 7. 版权提醒

- 直传**原创内容**是安全的。
- 若直传的是**第三方内容**（搬运），发布前需注意 YouTube **Content ID** 与
  **reused content（重复使用内容）** 政策，可能导致限流、下架或无法开通获利；发布前务必确认授权与合规。

