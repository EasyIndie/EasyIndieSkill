# 统一工作目录方案（磁盘文件治理）

> 提案 v1 · 2026-09-12 · 状态：**待老板拍板**
> 依据：老板提问「目前是否有统一的工作目录，避免在磁盘上乱放文件不好统一管理」

---

## 0. 一页话

**现状**：没有统一工作区。内容业务文件散在 7 处，另有 6 个报告 md 直接躺在家目录根。
**建议**：建 **`~/EasyIndie/`** 作为内容业务唯一工作区（inbox → work → ready → published 生命周期），**运行凭据仍留 `~/.hermes/youtube/`**（安全边界），两边用软链互通、脚本默认路径改指业务盘；同时把散落文件归位。
**关键原则**：只统一「**新产生的内容/产物**」+ 归位散落文件；**不动已经能跑的项目目录**（避免踩绝对路径/虚拟环境依赖）。

---

## 1. 现状盘点（2026-09-12 实测）

### 1.1 内容业务相关（本次治理重点）

| 位置 | 体积 | 内容 | 判定 |
|:--|:--|:--|:--|
| `~/.hermes/youtube/` | **439 MB** | `inbox/`（飞书落盘附件 + 加工 asset 目录）、`tmp/`（metaJSON）、`accounts/`、`ledger.csv`、`retired/`、`feishu.yaml` | ⚠️ **业务文件与运行凭据混在一起**；inbox 里同时塞着「原始附件」和「加工产物」 |
| `~/Downloads/` | 17 MB | 截图 PNG、ChatGPT 导出、EasyOPC banner、**`$RECYCLE.BIN` 残留目录** | ⚠️ 混杂；Downloads 只该做「中转站」 |
| `~/EasyIndieSkill/` | 900 KB | 技能 git 工作副本 | ✅ 合理，但可归入业务根 |
| 家目录根 `~/*.md` | 6 个文件 | `orzmc_巡检试运行报告_20260909.md`、`orzmc-windows-collab-setup.md`、`hermes-windows-migration-prompt.md`、`im-gateway-handoff.md`、`grimac-config-verify-20260902.md`、`orzmc-config-review-20260902.md` | ❌ **报告散落在根目录** |
| `/tmp` | — | agent 临时脚本/brief（`brief_*.md`、`diag_*.py`、`fsize_*.sh`…） | ✅ 临时目录本就该如此（重启即清） |

### 1.2 其它常驻目录（本次**不动**，但列出供老板决定）

| 位置 | 体积 | 内容 | 备注 |
|:--|:--|:--|:--|
| `~/Library` | 11 GB | 系统/应用数据 | 不动 |
| `~/Documents/OrzMusic` | 1.2 GB | 项目 | 能跑，不动（如要迁另议） |
| `~/Documents/EasyAI` | 287 MB | 项目 | 同上 |
| `~/Documents/EasySticker` `EasyTeam` | 30 MB | 项目 | 同上 |
| `~/minecraft` | 779 MB | MC 启动器数据（versions/java/cache） | 疑似自定义启动器目录，不影响就不动 |
| `~/OrzMC` `~/OrzMCAdmin` `~/minecraft-bot` | 407 MB / 7.7 MB / 464 MB | MC 相关代码与机器人工作区 | 能跑，不动 |
| `~/usr/local` | 119 MB | 疑似某次 `--prefix=$HOME/usr` 的安装残留 | ⚠️ **疑似残留**，待老板确认可清 |
| `~/profile_default` | 110 MB | Chromium 自动化用的 user-data-dir（Default/segmentation_platform/DevToolsActivePort） | ⚠️ **疑似浏览器自动化残留**，待确认可清 |
| `~/apache-maven-3.9.16` `~/go` | 11 MB / 22 MB | 工具链 | 不动 |
| `~/Movies` `~/Doubao` | 20 KB / 0 B | `desktop.ini`、anydesk 软链、空 skills | ⚠️ Windows 迁移残留，可清 |
| `~/.hermes/cache` | 336 KB | Hermes 附件缓存（documents 为空） | 不动 |

### 1.3 磁盘水位

`/` 113 GB 总量，已用 8.8 GB，可用 **52 GB**（15%）→ 空间不紧张，**痛点是「找不到、难管理」，不是「放不下」**。

---

## 2. 方案对比

| # | 方案 | 改动量 | 优点 | 缺点 | 结论 |
|:--|:--|:--:|:--|:--|:--|
| **A** | **建 `~/EasyIndie/` 业务根 + 生命周期分层 + 归位散落文件**（运行凭据留 `~/.hermes`，软链互通） | 中 | 业务可见可管、内容与凭据分离、脚本向后兼容、风险可控 | 要跑一次迁移（可脚本化） | ✅ **推荐** |
| B | 全部塞进 `~/.hermes/` 之下 | 小 | 零散落 | 隐藏目录不可见，人不好管；凭据/业务继续混 | ❌ |
| C | 只清理散落文件，不建新结构 | 极小 | 零风险 | 结构仍乱，下次照样散 | ❌（可作 A 的第一步） |

---

## 3. 推荐方案 A 的目标结构

```
~/EasyIndie/                        # 内容业务唯一工作区（可见、可备份、可整体挪盘）
├── inbox/                          # 待处理素材（飞书直传落盘 / 本机投递）
│   └── YYYYMMDD/                   #   按天分目录（现 from-feishu/<日期> 的结构保留）
├── work/                           # 加工中（asset 目录：source/output/cover/asset.json）
├── ready/                          # 已加工待发布（出卡片确认的素材）
├── published/                      # 已发布成品（按 YYYY-MM 归档）
├── covers/                         # 封面库（可复用素材）
├── reports/                        # 报告与方案（含现散在 ~ 根的 6 个 md）
├── docs/                           # 说明文档
└── skill/                          # 技能 git 工作副本（现 ~/EasyIndieSkill 迁入）

~/.hermes/youtube/                  # 运行数据与凭据（隐藏、不进业务盘）
├── accounts/<name>/{request.token, account.yaml}
├── ledger.csv                      # 上传台账
├── feishu.yaml / feishu_fetched.json
├── retired/
├── tmp/                            # metaJSON 等中间件
├── inbox -> ~/EasyIndie/inbox      # ← 软链（向后兼容，脚本默认路径不变也能跑）
└── work  -> ~/EasyIndie/work       # ← 软链
```

**分层理由**

| 层 | 放什么 | 为什么 |
|:--|:--|:--|
| `~/EasyIndie/` | 素材、成品、封面、报告 | 业务资产：要能一眼看见、能整体备份/挪盘 |
| `~/.hermes/youtube/` | token、账号档案、台账、状态 | 凭据与运行状态：保持隐藏，避免误传/误删 |

**素材生命周期（配套规则，写进技能）**

```
飞书直传/本机投递 → inbox/ → youtube_ingest → work/<asset_id>/ → 出卡片 → ready/ → 上传成功 → published/YYYY-MM/
                                                              ↘ 取消/过期 → 按 LRU 清理（默认阈值 500 MB 可用空间）
```

**规则三条**

1. agent 产出物一律落 `~/EasyIndie/`（`inbox/work/ready/published/covers/reports`）；**临时文件一律 `/tmp`**（重启即清）
2. 上传成功后素材从 `ready/` 移到 `published/YYYY-MM/`，台账里保留路径（可回溯）
3. 磁盘清理只针对 `inbox/`（未采用素材）与 `published/` 超期归档，**永不动 `work/ready` 里待处理的**

---

## 4. 落地清单（批准后执行，约 30 分钟）

1. **建目录树** `~/EasyIndie/{inbox,work,ready,published,covers,reports,docs}`
2. **迁数据**（`mv`，同盘秒级）：
   - `~/.hermes/youtube/inbox/*` → `~/EasyIndie/{inbox,work}/`（原始附件→inbox，asset 目录→work）
   - 建软链 `~/.hermes/youtube/inbox -> ~/EasyIndie/inbox`、`work -> ~/EasyIndie/work`
3. **脚本默认路径切换**：`youtube_ingest.py --out-dir`、`feishu_fetch_attachment.py --out-dir` 默认值改指业务盘（env 仍可覆盖）→ 需一次小改（交 pi）+ 复跑测试
4. **归位散落文件**：`~/*.md`（6 个）→ `~/EasyIndie/reports/`（OrzMC 主题的另可归 `~/OrzMC/docs/`）
5. **`~/EasyIndieSkill` → `~/EasyIndie/skill`**（bisync 脚本路径同步更新 + cron 验证）
6. **清理（需单独批准，逐项确认）**：
   - `~/Downloads/$RECYCLE.BIN`（外置盘残留）、`~/Movies/desktop.ini`、`~/Doubao/skills`(空)
   - 待确认：`~/usr/local`（119 MB）、`~/profile_default`（110 MB）
   - `~/Downloads` 里的截图/ChatGPT 导出 → 归档进 `~/EasyIndie/reports/attachments/` 或删
7. **沉淀**：本方案 + 目录约定写进 `easyindie` 技能（含生命周期与清理规则），记忆里加一条「业务文件统一 `~/EasyIndie/`」

---

## 5. 待老板拍板

| # | 决策项 | 建议 |
|:--|:--|:--|
| **#1** | 是否采用方案 A（建 `~/EasyIndie/` 业务根 + 软链互通） | 建议采用 |
| **#2** | 业务根名字用 `~/EasyIndie/` 还是别的（如 `~/Work/`、`~/Content/`） | 建议 `~/EasyIndie/`（与品牌/项目一致） |
| **#3** | `~/EasyIndieSkill`（技能工作副本）是否迁入 `~/EasyIndie/skill/` | 建议迁（需同步改 bisync 路径） |
| **#4** | 家目录根 6 个 md 报告 → `~/EasyIndie/reports/`？OrzMC 主题的另归 `~/OrzMC/docs/`？ | 建议全归 reports，再按主题分文件 |
| **#5** | 疑似残留是否清理：`~/usr/local`(119MB)、`~/profile_default`(110MB)、`$RECYCLE.BIN`、`~/Movies/desktop.ini`、空 `~/Doubao` | 建议逐个确认后清（我可以先生成「这些目录里到底有什么」的明细） |
| **#6** | `~/Downloads` 定位：只做中转站（SMB 共享落点），东西定期归档/清空？ | 建议是 |
| **#7** | 是否顺手迁移 `~/Documents/{OrzMusic,EasyAI,EasySticker,EasyTeam}` 到统一根 | 建议**暂不迁**（有绝对路径/构建依赖风险，单独评估） |
