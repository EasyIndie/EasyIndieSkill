# 工作目录规范（统一布局）

> 生效：2026-09-12（老板批准方案 A）· 状态：**已落地**
> 关联技能：`easyindie`（内容业务）／`orzmc`（MC 业务）

## 一、三层分离

### 1. 业务工作区 `~/EasyIndie/`（可见 · 可整体备份/挪盘）

| 子目录 | 用途 | 写入口 |
|:--|:--|:--|
| `inbox/` | **待处理原始素材** | 飞书直传自动落盘 → `inbox/from-feishu/YYYYMMDD/`；SMB/手动投递直接放这里 |
| `work/` | **加工中 asset 目录**（`source.*` / `output.*` / `cover.jpg` / `asset.json`） | `youtube_ingest.py` 默认输出 |
| `ready/` | 加工完成待发布 | 人工/流程确认后从 work 移入 |
| `published/YYYY-MM/` | 已发布成品归档 | 发布成功后归位 |
| `covers/` | 封面库（复用素材） | 手工/自动化 |
| `reports/orzmc/`、`reports/hermes/` | 报告与方案全文 | 家目录根 6 个 .md 已迁入（2026-09-12） |
| `docs/` | 说明文档 | — |

### 2. 运行数据与凭据 `~/.hermes/youtube/`（隐藏 · **不进业务盘**）

`accounts/<name>/{request.token,account.yaml}`、`ledger.csv`、`feishu.yaml`、`feishu_fetched.json`、`retired/`、`tmp/`

**兼容软链**（脚本按旧路径写入 → 自动落到业务盘）：

```
~/.hermes/youtube/inbox -> ~/EasyIndie/inbox
~/.hermes/youtube/work  -> ~/EasyIndie/work
```

### 3. 临时区 `/tmp`

agent 一次性脚本 / brief / 诊断文件。**任务结束即清**，重启自动消失。

## 二、路径优先级（脚本解析顺序）

| 脚本 | 优先级 |
|:--|:--|
| `youtube_ingest.py` | CLI `--out-dir` > `$EASYINDIE_WORK` > `~/EasyIndie/work` |
| `feishu_fetch_attachment.py` | CLI `--out-dir` > `$FEISHU_INBOX_ROOT` > `feishu.yaml:inbox_root` > `~/EasyIndie/inbox/from-feishu` |

> 历史坑：`feishu.yaml` 的 `inbox_root` 键曾经是**死配置**（脚本只读 `default_chat_id`），2026-09-12 已打通。

## 三、素材生命周期

```
inbox（原始）
  → work（加工：asmr/raw/clip/audio 编码 + 封面 + metaJSON）
  → ready（待发布，人工确认标题）
  → published/YYYY-MM（发布成功归档）
  → 定期清理（默认保留 30 天，LRU 优先清最大最旧）
```

**投递通道选择**（按体积）

| 体积 | 通道 |
|:--|:--|
| ≤100 MB | 飞书直传（Hermes 自动收，≤30MB bot 回传可用） |
| 100 MB – 1 GB | `feishu_fetch_attachment.py` 兜底 或 SMB「下载」共享 |
| >1 GB / 多 GB | SMB「下载」共享 或本机目录（零内存风险） |

## 四、家目录清理记录（2026-09-12）

| 项 | 体积 | 处置 | 依据 |
|:--|:--|:--|:--|
| `~/usr/local/bin/hugo` | 119 MB | **删** | 孤儿副本（brew 被 go pin 卡住时期的替代品）；brew 版 0.165.0 `+extended+withdeploy` 同版本且已在 PATH，`hugo -d` 实测构建 93 页通过 |
| `~/profile_default` | 110 MB | **删** | 6 月 Chrome 自动化残留（无进程占用） |
| `~/Doubao/` | 0 | **删** | 空目录 |
| `~/Downloads/$RECYCLE.BIN`、`~/Movies/desktop.ini` | 4 KB | **删**（sudo） | root 属主 Windows 残留 |
| `~/Downloads/*.png` 13 个 | 17 MB | **归档** → `~/Pictures/归档-20260912/` | Downloads 只做中转站 |
| 家目录根 6 个 `.md` | 52 KB | **迁** → `~/EasyIndie/reports/{orzmc,hermes}/` | 老板 #4 |
| `~/EasyIndieSkill`（技能 git 工作副本） | — | **不动** | 老板 #3（含 bisync 路径，迁动有 cron 成本） |
| `~/Documents/{OrzMusic,EasyAI,EasySticker,EasyTeam}` | 1.5 GB | **不动** | 老板 #7 |
| `~/minecraft`、`~/OrzMC*`、`~/minecraft-bot` | ~1.7 GB | **不动** | 在跑的项目 |

## 五、约定（新文件往哪放）

1. **业务产物一律进 `~/EasyIndie/`** —— 不再往家目录根、`~/Downloads` 散放
2. `~/Downloads` = **中转站**（SMB 落点/浏览器下载），定期清空归档
3. agent 临时文件一律 `/tmp`，任务结束即清
4. 凭据 / 真实 chat_id **永不**进业务盘与公开技能仓库
5. 需要长期保留的报告 → `~/EasyIndie/reports/<主题>/`
