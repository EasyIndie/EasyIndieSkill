# EasyIndie 公开站点（GitHub Pages）— 承接 YouTube/OAuth 相关页面

**2026-09-12 建立。** 用途：Google OAuth「应用首页 / 隐私政策」等对外页面；也是 OAuth 发布状态的
配套要求（Google 要求自有域名 + 可访问的政策页）。

## 站点档案

| 项 | 值 |
|:--|:--|
| 线上地址 | **https://easyindie.jokerhub.cn/** |
| 仓库 / 分支 | `EasyIndie/EasyContentCreator` → **`gh-pages`**（孤儿分支，静态站；**不碰 main**）|
| Pages 配置 | Source = `gh-pages/root`，build_type=legacy，https_enforced=true |
| 自定义域名 | `easyindie.jokerhub.cn`（CNAME 文件由 GitHub 自动写入分支）|
| **应用名称** | **`EasyUploader`**（品牌/网站 = `EasyIndie`）—— console App name 必须与首页 `<h1>`/`<title>` 上的字符串**完全一致**，改任一处都要同步另一处 |
| DNS | Cloudflare：`CNAME easyindie → easyindie.github.io`，**必须灰云 DNS only**（橙云签不出证书）|
| 页面 | `/`（首页·应用介绍）、`/privacy.html`（隐私政策）、`/terms.html`（服务条款）、`/assets/style.css`、`.nojekyll` |
| 旧地址 | `https://easyindie.github.io/EasyContentCreator/` → 301 到自有域（正常）|

> 参考先例：`blog.jokerhub.cn` 也是 GitHub Pages + 灰云（→ `wangzhizhou.github.io`）。
> ⚠️ `jokerhub.cn` 存在通配符 `*.jokerhub.cn`（指向隧道、橙云）；精确记录 `easyindie` 会覆盖它，
> 但**必须灰云**，否则 GitHub 无法签 HTTPS 证书。

## 本机验证坑：TUN 代理 fake-ip 会「假性打不开」本站

本机跑着 TUN 代理（`utun3` + fake-ip DNS `198.18.0.2`，`198.18.0/15` 走 utun3）。
实测：`easyindie.jokerhub.cn` 与 `www.jokerhub.cn` 被解析成 `198.18.x.x` → 连接失败（HTTP 000，
`SSL_ERROR_SYSCALL`）；而 `blog.jokerhub.cn`、`mcs.jokerhub.cn` 同机正常 200。
**站点本身没问题**（公网正常）。验证时绕开本机解析：

```bash
curl --resolve easyindie.jokerhub.cn:443:185.199.108.153 https://easyindie.jokerhub.cn/privacy.html   # → 200
curl -H 'accept: application/dns-json' "https://cloudflare-dns.com/dns-query?name=easyindie.jokerhub.cn&type=A"  # DoH 看真实记录
```
永久解法二选一：代理客户端把 `*.jokerhub.cn` 设为 DIRECT；或 `/etc/hosts` 固定
`185.199.108.153 easyindie.jokerhub.cn`。


## 更新站点内容

```bash
# 站点文件源在本地 /tmp 是易失的 → 长期维护请从分支拉取
gh repo clone EasyIndie/EasyContentCreator /tmp/ecc && cd /tmp/ecc
git checkout gh-pages            # 站点唯一在 gh-pages 分支
# 改 index.html / privacy.html / terms.html / assets/style.css
git add -A && git commit -m "docs(pages): <改动>" && git push origin gh-pages
```
- 推完约 30–60 秒 Pages 自动重建；用 `gh api repos/EasyIndie/EasyContentCreator/pages --jq .status` 看 `built`。
- 改自定义域名：`gh api -X PUT repos/EasyIndie/EasyContentCreator/pages -f cname=<域名>`。

## 与 Google OAuth 的关系（重要）

- Branding 页必填：**App name / User support email / Application home page / Application privacy policy link**
  → 首页填 `https://easyindie.jokerhub.cn/`，隐私政策填 `https://easyindie.jokerhub.cn/privacy.html`。
- **Authorized domains 填 `jokerhub.cn`（顶级域，不是子域）**，且该域必须在 **Search Console** 中验证过，
  且验证用的 Google 账号要与持有**该 GCP 项目**（即 client_id 所属项目）的账号**一致**。
- Search Console 验证方式（二选一）：
  - **Domain 属性**（推荐）：Search Console 加 Domain 属性 `jokerhub.cn` → 取 TXT 值 →
    Cloudflare 加 `TXT @ google-site-verification=…` → 点验证。**TXT 建议长期保留**（删了会丢验证）。
  - HTML 文件验证：把验证文件推到 gh-pages 根目录（本项目已可用此路，无需 DNS 权限）。
- 隐私政策内容要求（YouTube API Services 必含）：所用 scope、数据用途、存储位置、
  **撤销授权入口**（https://myaccount.google.com/permissions）、Google 隐私权政策 + YouTube 服务条款 + Limited Use 声明。

## 隐私政策模板要点（已落地在 privacy.html）

1 适用范围 → 2 访问的信息（仅 access/refresh token + scope `youtube.force-ssl`）→ 3 使用目的（仅上传/管理自有频道）
→ 4 存储与保护（token 只存本地受限文件、HTTPS）→ 5 保留与删除 + 撤销授权 → 6 第三方服务（YouTube API Services、
Google Privacy Policy、YouTube ToS、Limited Use）→ 7 未成年人 → 8 变更 → 9 联系方式。

⚠️ 联系方式邮箱必须真实可用（写死占位符会被 Google 复核或用户投诉）；修改时同步 `index.html`/`privacy.html`/`terms.html` 三处。
