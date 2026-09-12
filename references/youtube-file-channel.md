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

## 4. 支持格式与建议

- 视频：`mp4` / `mov` / `mkv` / `webm` / `avi`（以及 `m4v/flv/wmv/ts`）。
  - 建议优先发 **mp4（H.264 + AAC）**，兼容性最好、`raw` 模式可直接复制、无需转码。
  - 非 mp4 视频走 `raw` 时会先 `-c copy` remux 到 mp4，失败再回退 H.264/AAC 转码（会耗时）。
- 音频：`mp3` / `m4a` / `wav` / `flac` / `ogg`（以及 `aac/opus/wma`）。
  - `wav`/`flac` 体积大，长音频建议先自行压成 `m4a`/`mp3` 再发，或直接用 `--mode audio` 输出 192k MP3。

## 5. 飞书消息附件大小上限（重要）

- **首次实测记录位（待填）**：
  > 待实测：老板首次发大文件时记录实际可传上限与失败提示。
  > 记录项建议：文件大小、扩展名、飞书报错/无反应、是否收到 `[Attachment: ...]`、落盘路径与大小是否一致。
- 未实测前，**默认按保守估计处理**：单个附件过大时，飞书客户端可能直接拒发或长时间卡在上传，
  Hermes 侧则可能收不到附件（无 `[Attachment: ...]`）。遇到这种情况先看下一节「超限替代通道」。

### 超限替代通道（附件发不出来时）

1. **本机目录投递**：把文件放到本机 `~/Downloads` 或 `~/.hermes/youtube/inbox`，
   再让 agent 用该路径跑 `youtube_ingest.py`（等价于通道 2 的输入）。
2. **macOS SMB 共享**：开启「文件共享」，共享名 **「下载」**；老板从电脑/手机上传到该共享目录后，
   agent 按上面的「本机目录投递」处理。
3. 若文件本身是网络可访问的链接，可改走**链接通道**（通道 1）。

## 6. 常见失败与处置

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

