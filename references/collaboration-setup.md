# EasyIndie 技能多设备协作开启流程

> 2026-09-09 沉淀（方法论出自 skill-git-export 7c「多设备双向协作」，orzmc 已实测跑通）。
> 触发：老板要把本技能放到多台设备的 Hermes 上协作迭代（如 Mac + Windows），或本技能要同步到 GitHub 供多机复用。
> **✅ 已落地（2026-09-09）**：仓库 = `EasyIndie/EasyIndieSkill`（PUBLIC，2026-08-10 建仓推 v1.0.0）；Mac 侧 A=`~/EasyIndieSkill`、B=技能目录；双向脚本 `~/.hermes/scripts/easyindie_bisync.sh`；cron「easyindie 技能双向同步」every 60m（no_agent）。Windows 等新设备接入 = 下文步骤 6 模板（路径换 easyindie）。

## 核心模型（public 单仓库 + 占位符双向转换）

```
GitHub repo（PUBLIC · 占位符版）       ← 仓库归属届时老板拍板（EasyIndie org 或 wangzhizhou）
     ▲ git push / git pull
[设备 A]  git 工作副本 ⇄ 技能目录（真实版，Hermes 直接读/改）
[设备 B]  同
watchdog（cron no_agent every 60m）双向：
  ① PULL 先行：fetch → pull → dec(占位符→真实) 刷新技能目录
  ② PUSH 后行：技能目录改动 → enc(真实→占位符) 镜像 → 复扫门禁 → commit+push
```

转换 = **确定性 sed 映射表**（不是 LLM 猜测）；设备本地永远真实版、GitHub 永远占位符版。

## 本技能的真实值盘点（2026-09-09，开协作最简的依据）

| 检查项 | 结论 |
|---|---|
| client_id / API key / 频道 ID | **零**（凭据全在 `~/.hermes/youtube/` 外部文件，不入技能）✓ |
| 路径 | 仅 `~/.hermes/youtube`（通用，无用户名）✓ |
| 待占位符化 | 基本无 → 内容可直接 public，映射表几乎为空 |

## 完整流程（开协作时执行）

1. **建仓库**：`gh repo create <org>/easyindie-skills --public`（归属待老板拍板）；仓库标配 README/LICENSE/.gitignore
2. **设备 A（如 Mac）**：
   - 技能目录 `~/.hermes/skills/media/easyindie` → `git clone` 仓库到该目录？❌ 不行——技能目录是真实版生成物。
   - 正确：git 工作副本放独立目录（如 `~/easyindie-skills`），技能目录由 dec 生成（参考 orzmc：A=~/OrzMCAdmin、B=~/.hermes/skills/gaming/orzmc）
3. **双向脚本**：复制 `~/.hermes/scripts/orzmc_bisync.sh` → 改路径默认值（或设 `ORZMC_SKILL_DIR/ORZMC_REPO_DIR` 等价变量——脚本若写死 orzmc 路径，改为 easyindie 版 `easyindie_bisync.sh`）：
   - 拷贝范围：easyindie 是 SKILL.md + references/ + scripts/（scripts/common、processors 子目录要在拷贝清单登记！）
   - enc/dec 规则：按需（本技能目前近乎零映射，规则可留空数组）
4. **复扫门禁**：grep 真实值模式（届时按实际盘点：频道 ID/账号/邮箱/token 路径）
5. **cron**：每端 `every 60m` no_agent 调 bisync
6. **Windows 等设备接入**：gh auth → clone → dec 生成技能目录 → cron（模板见 `~/orzmc-windows-collab-setup.md`，路径换成 easyindie）
7. **验证**：一端改技能 → 跑 bisync → 他端 pull 后技能含改动（dec 真实版）

## ⚠️ 铁律（orzmc 实测教训，勿重踩）

1. **PULL 必须先于 PUSH**：镜像模型下先 PUSH 会把"远端新文件（本地还没有）"当多余删掉并推回——删了他端提交
2. **删除保护 v2**：被删文件在技能目录已不存在 = 本端有意删除（放行）；仍存在 = 镜像异常（中止）
3. **仓库元文件**（README/LICENSE/.gitignore）排除在镜像外（技能目录没有它们），仓库侧手工维护
4. **含脱敏规则/映射表的脚本不能进 public 仓库**（复扫门禁命中自身）——从共享目录/私有渠道交付
5. **新真实值纪律**：技能里出现新账号/ID/凭据 → 加映射表（两端脚本同步）；不加 = 复扫门禁中止提示
6. 占位符化规则一律"替换"不"删除"（删除不可逆丢信息，ATMiLQGZ 教训）
7. bash 3.2 兼容（macOS 自带）与 GNU sed（Windows Git Bash）差异：脚本内置 `sed -i` 平台分支
8. git 提交身份：public 历史不暴露真实邮箱 → 建议 GitHub noreply 邮箱 + 双端 user.name 区分设备

## 参考资产

- 方法论：skill-git-export 技能 7c 节
- 实现：`~/.hermes/scripts/orzmc_bisync.sh`（macOS/Windows Git Bash 通用）
- Windows 接入模板：`~/orzmc-windows-collab-setup.md`
- orzmc 实战仓库：`github.com/OrzMC/OrzMCAdmin`（占位符版在库、设备本地 dec 真实版）
