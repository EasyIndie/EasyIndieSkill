# Google OAuth 应用：Testing → Production 全流程（含 token 失效根治）

> **2026-09-12 由独立技能 `google-oauth-app-publishing`（devops 类）合并入本技能**（老板决策：内容/自媒体相关归 EasyIndie）。
> 适用：任何 Google API 应用（YouTube/Drive/Gmail…）的授权发布运维；为方便跨项目复用，脚本与模板做了**参数化**。
> 配套文件：`scripts/google_token_refresh.py`（刷新）、`scripts/google_oauth_reauth.py`（重授权）。
> **政策站页面不预置模板** —— 执行时按第 2 节清单**现场生成** HTML/CSS（老板 2026-09-12 决策：技能库不存页面文件，省同步带宽）。

## When to Use

- 定时任务/脚本报 `invalid_grant`，或 refresh token **周期性地（≈7 天）失效**
- 要把 OAuth 应用从 **Testing** 发布为 **In production**（让 refresh token 不再过期）
- 点 Publish 时被 Google **品牌验证** 驳回（首页未注册到您名下 / 应用名不一致 / 首页未说明用途…）
- 需要给 OAuth 应用搭「**应用首页 + 隐私政策**」政策站（自有域要求）

## 0. 一句话结论

> **Testing 状态的 OAuth 应用，其 refresh token 寿命固定 7 天**（604800 秒，与是否活跃、刷新多频繁**无关**）。
> 唯一根治：**Publishing status 改 In production**（免费、**无需通过 Google 验证审核**）→ 然后**重授权一次**。
> 之后 refresh token 永不过期，一次授权长期有效。

## 1. 先诊断（拿证据，不要猜）

### 1.1 `refresh_token_expires_in` 是**剩余倒计时**，不是总寿命

```bash
python3 -c "import json;t=json.load(open('$HOME/.hermes/youtube/request.token'));print({k:t.get(k) for k in ('expiry','refresh_token_expires_in','scope')})"
```
- 新签发时 ≈ **604800** → 铁证：应用处于 Testing
- 旧 token 里的 2xxxxx 之类是「当时还差多少秒到期」，**别误读成寿命**
- 反推签发时刻 = `死亡时刻 - 604800`，可与「最近一次成功刷新」时间线交叉验证

### 1.2 实测刷新（90 秒拿真因）

```bash
python3 - <<'PY'
import json, urllib.request, urllib.parse, urllib.error, os
d = json.load(open(os.path.expanduser('~/.hermes/youtube/video_uploader.json'))); s = d.get('installed', d)
t = json.load(open(os.path.expanduser('~/.hermes/youtube/request.token')))
data = urllib.parse.urlencode({"client_id": s["client_id"], "client_secret": s["client_secret"],
                               "refresh_token": t["refresh_token"], "grant_type": "refresh_token"}).encode()
req = urllib.request.Request("https://oauth2.googleapis.com/token", data=data, method="POST")
try:
    r = json.loads(urllib.request.urlopen(req, timeout=20).read())
    print("OK keys:", sorted(r.keys()))
    print("refresh_token_expires_in =", r.get("refresh_token_expires_in"))   # 缺失 = Production ✅
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode())
PY
```
- `{"error":"invalid_grant"}` = refresh token **已死，重试无效**（必须重授权）
- 响应体里带 `refresh_token_expires_in` = 仍是 Testing；**字段缺失 = Production 生效** ← 最硬的验收信号

### 1.3 ⚠️ 脚本必须读 HTTPError 响应体

`urllib.error.HTTPError` 是 `URLError` 的**子类** → 若只 `except URLError` 而不读 `e.read()`，
日志里只剩 `HTTP Error 400`，真因（`invalid_grant`）被吞掉。**本项目为此连败 6 次、静默 3 周无法定位。**
本技能 `scripts/google_token_refresh.py` 已修好（单独捕获 HTTPError + 读响应体 + 给根因与修法）。

## 2. 搭政策站（Google 要求：自有域 + 首页 + 隐私政策）

### 2.1 托管（推荐 GitHub Pages + 自有域，零费用）

```bash
# 1) 站点放「孤儿 gh-pages 分支」（不碰 main，符合本项目分支规范）
cd /tmp/site && git init -q -b gh-pages && git add -A
git -c user.name=<user> -c user.email=<noreply> commit -q -m "docs(pages): add policy site"
git remote add origin https://github.com/<org>/<repo>.git && git push -u origin gh-pages   # 需先 gh auth setup-git

# 2) 开 Pages（推到 gh-pages 后常会自动开启）
gh api -X POST repos/<org>/<repo>/pages -f 'source[branch]=gh-pages' -f 'source[path]=/'

# 3) 绑自有子域（先 DNS、后 GitHub 的顺序很重要）
gh api -X PUT repos/<org>/<repo>/pages -f cname=<sub>.<domain>
gh api -X PUT repos/<org>/<repo>/pages -F https_enforced=true
```
Cloudflare DNS：`CNAME <sub> → <org>.github.io`，**代理状态必须灰云（DNS only）** —— 橙云会让 GitHub 签不出证书。
⚠️ 若 zone 里有**通配符 `*`**（例如指向隧道、橙云），更精确的子域记录可覆盖它，但**仍须灰云**。
⚠️ 一定要**先加 DNS 再设 GitHub 自定义域**，否则 `*.github.io` 立刻 301 到尚未生效的域，站点看起来「挂了」。

### 2.2 页面必备（Google 官方 home page 要求）

| 要求 | 落地 |
|:--|:--|
| 准确代表品牌/应用 | 首页 `<title>` + `<h1>` 与 console **App name 完全一致** |
| 完整描述应用功能 | 一节「这个应用做什么」 |
| 透明说明为何需要 Google 用户数据 | 一节列出 scope 与用途，声明不用于广告/画像/共享 |
| 托管在**已验证的自有域** | 不能用 Google Sites / Facebook 等第三方平台 |
| 首页含**隐私政策链接**，且与 consent screen 填的一致 | 显著位置放链接 |
| 无需登录即可见 | 静态公开页 |

隐私政策必备 9 节（**执行时现场生成**，技能内不预置模板文件 —— 老板 2026-09-12 决策）：适用范围 / 访问的信息（scope）/ 使用目的 /
存储与保护 / 保留与删除 + **撤销授权入口**（`https://myaccount.google.com/permissions`）/
第三方服务（YouTube API Services + Google Privacy Policy + YouTube ToS + Limited Use）/
未成年人 / 变更 / 联系方式。

### 页面骨架规格（现场生成清单，避免每次重新构思）

| 文件 | 必备内容 |
|:--|:--|
| `index.html` | `<title>` + `<h1>` 用**与 console 完全一致的 App name**；「应用名称」卡片（注明所属品牌）；「这个应用做什么」；「为什么需要访问您的 Google 账号数据」（列 scope + 声明不用于广告/画像/共享）；「谁在使用」；政策链接区；联系方式（公开 issue）；品牌与版权脚注 |
| `privacy.html` | 上述 9 节；第 2 节写明 scope 全串；第 5 节给撤销授权超链接；第 6 节写 YouTube API Services + Google 隐私政策 + YouTube ToS + User Data Policy(Limited Use) + 英文声明段；第 9 节 = 公开 issue 渠道（**不放私人邮箱**）|
| `terms.html` | 服务内容 / 使用许可（含 YouTube ToS 链接）/ 知识产权 / 免责声明 / 第三方服务 / 条款变更 / 联系方式 |
| `assets/style.css` | 自包含（零外部依赖）+ 深色模式适配；站点根放 `.nojekyll` 避免 Jekyll 处理 |

> 占位符约定：`{{APP_NAME}}` `{{BRAND}}` `{{DOMAIN}}` `{{CONTACT_URL}}` `{{DATA_SCOPE_TECH}}` `{{DATA_SCOPE_HUMAN}}` —— 生成后**务必替换为真实值**，别把占位符发布上线（曾用 `CONTACT_EMAIL_PLACEHOLDER` 差点上线）。

### 2.3 联系方式别放私人邮箱

公开页面放私人邮箱 = 爬虫收集 + 合规观感差。用**公开 issue / 表单页**做联系渠道（如
`github.com/<org>/<repo>/issues`）；提交 commit 时也用 GitHub noreply 邮箱，避免二次暴露。

## 3. Search Console 验证（Authorized domains 的前置条件）

- **Domain 属性**（DNS TXT，覆盖全部子域，最稳）：
  Search Console → 新增资源 → **网域** → 输入顶级域 → 复制 `google-site-verification=…` →
  Cloudflare 加 `TXT @ <整串>` → 点验证。**TXT 长期保留**（删掉会丢验证）。
- **URL 前缀属性**（HTML 文件方式，不需要 DNS 权限）：把 Search Console 给的
  `googleXXXX.html` 推到站点根目录 → 点验证。品牌验证报「首页未注册到您名下」且 Domain 属性已就绪时，
  追加一个 URL 前缀属性往往能立刻解决。
- ⚠️ 验证所用的 Google 账号**必须与持有该 GCP 项目的账号一致**。
- 复核（不依赖浏览器）：`curl -H 'accept: application/dns-json' "https://cloudflare-dns.com/dns-query?name=<domain>&type=TXT"`

## 4. 发布（新版 Google Auth Platform UI）

- 旧链接 `console.cloud.google.com/apis/credentials/consent` 会**自动跳转**到新版的
  **Google Auth Platform → Overview**，而**概览页没有发布按钮** → 这就是「找不到 Publish app」的原因。
- 发布按钮在 **Audience** 页：`https://console.cloud.google.com/auth/audience`（或概览页的 Publishing status 行）。
- **发布前置**：Branding 页必须完整，否则报
  *"To publish your app, you must complete your configuration on the Branding page"*。
  外部生产模式**强制**四项：**应用名称 / 支持邮箱 / 首页网址 / 隐私政策网址**（+ 开发者联系邮箱）。
- `Authorized domains` 填**顶级域**（不是子域），且需 Search Console 已验证。
- **全程免费**：发布、验证审核都不收费，无需绑结算账号。唯一「额度」是 API 配额
  （YouTube Data API：10,000 单位/天，上传 1 视频 ≈ 1,600 单位 ≈ 6 个/天，超限 403 不扣费）。

## 5. 品牌验证 findings → 修法（实测）

| Finding | 真因 | 修法 |
|:--|:--|:--|
| 首页网址「未注册到您的名下」 | 检查是**异步快照**；Search Console 验证晚于上次检查 | ① 直接**重试 Publish**；② 仍报 → 追加 **URL 前缀**属性 |
| 应用名称与首页上的应用名称不一致 | console App name 必须是首页上**可识别的同一字符串** | 两处统一：改 console App name，或把名称写进首页 `<title>`+`<h1>`+正文（推荐改**站点**，避免二次审阅）|
| 首页未说明应用用途 | 首页缺功能/数据用途描述 | 加「应用做什么 + 为何需要用户数据」两节 |
| 首页缺隐私政策链接 | — | 首页显著位置放政策链接，与 console 填的一致 |
| 首页需登录才能看 | — | 去掉登录墙或换公开首页 |
| 首页是短链/会跳转到别的域 | — | 用静态、不跳转的完整 URL |

⚠️ 品牌检查**异步**（提交后分钟~小时出结论），别反复点提交。
⚠️ **顺序**：**先发布成功 → 再重授权**；在 Testing 下重授权只能拿到 7 天 token，等于白跑一次授权（还会多触发一次 OAuth，用户最忌讳）。

## 6. 唯一一次重授权 + 闭环验证

```bash
python3 scripts/google_oauth_reauth.py            # 通用模板：读 client secrets → 打印授权 URL → localhost 回调 → 写 token → 自测刷新
```
- 浏览器必须与回调服务**同一台机器**（`http://localhost:<port>/`）；链接含 `prompt=consent` 才会签发**新** refresh token
- 出现「Google 尚未验证此应用」→ 点「高级 → 继续前往」；**只点一次**，避免重复授权触发风控
- 脚本会自动备份旧 token（`*.bak`），授权失败自动回滚
- 验收（硬信号）：刷新响应中 **不再出现 `refresh_token_expires_in`** → Production 生效 ✅
- 若该字段仍带 7 天读数 → Console 没真生效，**先回查状态，别重复授权**

## 7. 加固与运维（把「静默死亡」堵住）

- **`deliver: local` 是隐形杀手**：本项目 6 次失败一条通知都没有 → 关键 cron 任务一律
  `deliver: origin`（成功失败都通知），配合 `no_agent` 脚本。
- 脚本 watchdog：刷新成功时打印 refresh token **剩余寿命**，`<24h` 提前告警；
  捕获 `invalid_grant` 时直接输出根因 + 重授权命令 + 永久修复路径。
- **沙盒演练法**（改动 token 脚本后必做，绝不动真 token）：复制 token 到临时目录、
  把 `expiry` 伪造成过去 → `YOUTUBE_DIR=/tmp/x python3 script.py` 走完整刷新路径。
- **两份脚本同步**：技能 `scripts/` 与 `~/.hermes/scripts/`（cron 实际执行）必须一致，
  改完 `diff -q` 核对。覆盖用 `\cp -f`（本机 `cp` 有 `-i` alias，非交互环境会静默失败）。

## Pitfalls（全是踩过的）

- **本机 fake-ip / TUN 代理**（如 `utun3` + fake-ip DNS `198.18.0.2`）会把自有域解析成 `198.18.x.x` →
  本地 curl 返回 000、`SSL_ERROR_SYSCALL`，**并不代表站点故障**。验证要绕开本机解析：
  `curl --resolve <host>:443:185.199.108.153 https://<host>/`，或用 DoH 查真实记录。
- **`web_extract` 读不了 `support.google.com`**（被判「私有地址」）→ 用
  `curl -sL -o /tmp/x.html <url>` + `textutil -convert txt -stdout /tmp/x.html` 读官方文档。
- `urllib.error.HTTPError` ⊂ `URLError`（顺序写错就吞掉真因）。
- GitHub Pages 自定义域证书签发需要**灰云**；橙云下 GitHub 校验/签发都会失败。
- 政策页别放私人邮箱；commit 作者用 noreply。
- 品牌验证是异步的，别把「提交后仍显示旧 findings」当成没修好。

## 参考文件

- `scripts/google_oauth_reauth.py` — 通用一键重授权（参数化 scope/端口/凭据路径）
- `scripts/google_token_refresh.py` — 硬化版刷新脚本（可作 cron no_agent 任务）
- **政策站页面（index/privacy/terms/样式）不预置文件** —— 按第 2 节「页面骨架规格」**现场生成**（老板 2026-09-12 决策）
