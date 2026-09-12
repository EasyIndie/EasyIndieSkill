#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ytauto_accounts.py — YouTube 多账号档案注册表。

目录约定
--------
- 账号根目录：``$YT_ACCOUNTS_DIR``，默认 ``~/.hermes/youtube/accounts``
- 账号档案  ：``<accounts_dir>/<name>/account.yaml``
- token     ：``<accounts_dir>/<name>/request.token``（档案里给了 ``token_path`` 则用它）
- 凭据      ：档案里的 ``client_secrets``（``~`` 会展开）；未给则用
              ``$YOUTUBE_DIR/video_uploader.json``（默认 ``~/.hermes/youtube/video_uploader.json``）

真实性约束
----------
本文件只定义**结构与默认值**，不包含任何真实凭据 / 频道 ID / 邮箱。
真实值只存在于运行时目录 ``~/.hermes/youtube/``。

YAML 解析
---------
优先使用 PyYAML（``import yaml``）。若环境无 PyYAML，则回退到内置的极简解析器
``_mini_yaml()``。极简解析器**只支持本模块用到的子集**，限制如下：

1. 仅两层结构：顶层 ``key:`` 及其一层缩进子内容；更深缩进会被当作普通标量文本。
2. 标量：``key: value``、行内列表 ``key: [a, b]``、空值（后面跟缩进块）。
3. 块列表：``- item``（一层，不支持 ``- key: value`` 的对象列表）。
4. 块标量：``key: |``（保留换行）与 ``key: |-``（去尾换行）；不支持折叠 ``>``。
5. 只识别 ``#`` 注释（引号内的 ``#`` 不算；``#`` 前需为空白或行首）。
6. 不支持锚点/别名/多文档/引号转义/数字进制等高级语法。
7. 布尔：``true/false/yes/no``（不区分大小写）；``null/~`` → None；数字转 int/float。
"""

from __future__ import annotations

import os
import shutil
import string
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "AccountNotFound",
    "Account",
    "accounts_dir",
    "youtube_dir",
    "list_accounts",
    "load_account",
    "resolve_default",
    "migrate_legacy",
    "init_account",
    "account_path",
]

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "account.yaml.template"


class AccountNotFound(Exception):
    """账号不存在，或账号根目录为空。"""


# --------------------------------------------------------------------------- #
# 路径
# --------------------------------------------------------------------------- #
def youtube_dir() -> Path:
    """运行时目录（可在测试中用 YOUTUBE_DIR 覆盖）。"""
    return Path(os.path.expanduser(os.environ.get("YOUTUBE_DIR", "~/.hermes/youtube")))


def accounts_dir() -> Path:
    """账号根目录（``YT_ACCOUNTS_DIR`` 覆盖，否则 ``$YOUTUBE_DIR/accounts``）。"""
    override = os.environ.get("YT_ACCOUNTS_DIR")
    if override:
        return Path(os.path.expanduser(override))
    return youtube_dir() / "accounts"


def account_path(name: str, base: Optional[Path] = None) -> Path:
    base = base or accounts_dir()
    return base / name / "account.yaml"


# --------------------------------------------------------------------------- #
# Account 数据模型
# --------------------------------------------------------------------------- #
@dataclass
class Account:
    name: str
    display: str = ""
    channel_id: str = ""
    client_secrets: str = ""
    token_path: str = ""
    default_privacy: str = "unlisted"
    default_language: str = "zh"
    default_category: int = 24
    default_playlists: List[str] = field(default_factory=list)
    tags_pool: List[str] = field(default_factory=list)
    title_template: str = ""
    description_template: str = ""
    doc_status: str = "test"
    daily_publish_cap: int = 3
    extra: Dict[str, Any] = field(default_factory=dict)
    source_path: str = ""

    # -- 派生路径 ---------------------------------------------------------- #
    @property
    def directory(self) -> Path:
        if self.source_path:
            return Path(self.source_path).parent
        return accounts_dir() / self.name

    @property
    def token_file(self) -> Path:
        raw = self.token_path or str(self.directory / "request.token")
        raw = os.path.expanduser(os.path.expandvars(raw))
        p = Path(raw)
        if not p.is_absolute():
            p = self.directory / p
        return p

    @property
    def secrets_file(self) -> Path:
        if self.client_secrets:
            return Path(os.path.expanduser(os.path.expandvars(self.client_secrets)))
        return youtube_dir() / "video_uploader.json"

    def to_dict(self) -> Dict[str, Any]:
        return dict(
            name=self.name,
            display=self.display,
            channel_id=self.channel_id,
            client_secrets=self.client_secrets,
            token_path=str(self.token_file),
            default_privacy=self.default_privacy,
            default_language=self.default_language,
            default_category=self.default_category,
            default_playlists=list(self.default_playlists),
            tags_pool=list(self.tags_pool),
            title_template=self.title_template,
            description_template=self.description_template,
            doc_status=self.doc_status,
            daily_publish_cap=self.daily_publish_cap,
            extra=dict(self.extra),
            source_path=self.source_path,
        )


# --------------------------------------------------------------------------- #
# 极简 YAML 解析器（无 PyYAML 时回退）
# --------------------------------------------------------------------------- #
def _strip_comment(s: str) -> str:
    out: List[str] = []
    quote = None
    for i, c in enumerate(s):
        if quote:
            out.append(c)
            if c == quote:
                quote = None
            continue
        if c in ("'", '"'):
            quote = c
            out.append(c)
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            break
        else:
            out.append(c)
    return "".join(out).rstrip()


def _parse_scalar(raw: str) -> Any:
    v = raw.strip()
    if v == "":
        return None
    if v == "{}":
        return {}
    if v == "[]":
        return []
    if len(v) >= 2 and v[0] == "[" and v[-1] == "]":
        inner = v[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(x) for x in inner.split(",")]
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    low = v.lower()
    if low in ("true", "yes"):
        return True
    if low in ("false", "no"):
        return False
    if low in ("null", "~"):
        return None
    try:
        return int(v)
    except ValueError:
        pass
    try:
        return float(v)
    except ValueError:
        pass
    return v


def _parse_block(lines: List[str], base_indent: Optional[int]) -> Any:
    items = [l for l in lines if l.strip() != ""]
    if not items:
        return None
    if base_indent is None:
        base_indent = len(items[0]) - len(items[0].lstrip(" "))
    first = items[0][base_indent:].lstrip()
    if first.startswith("- ") or first == "-":
        result: List[Any] = []
        for l in items:
            content = l[base_indent:].strip()
            if content.startswith("- "):
                result.append(_parse_scalar(content[2:]))
            elif content == "-":
                result.append(None)
        return result
    # 字典（一层）
    out: Dict[str, Any] = {}
    for l in items:
        content = l[base_indent:].strip()
        content = _strip_comment(content)
        if not content or ":" not in content:
            continue
        k, _, val = content.partition(":")
        out[k.strip()] = _parse_scalar(val)
    return out


def _mini_yaml(text: str) -> Dict[str, Any]:
    """内置极简 YAML 解析器；支持范围见模块 docstring。"""
    result: Dict[str, Any] = {}
    lines = text.splitlines()
    i = 0
    n = len(lines)
    while i < n:
        raw = lines[i]
        i += 1
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if raw[0] in " \t":
            # 顶层出现意外缩进 → 跳过（极简解析器不支持）
            continue
        body = _strip_comment(raw)
        if not body.strip() or ":" not in body:
            continue
        key, _, val = body.partition(":")
        key = key.strip()
        val = val.strip()

        if val in ("|", "|-", "|+"):
            # 块标量：收集后续缩进行（原样保留相对缩进）
            scalar_lines: List[str] = []
            base = None
            while i < n:
                l = lines[i]
                if l.strip() == "":
                    scalar_lines.append("")
                    i += 1
                    continue
                ind = len(l) - len(l.lstrip(" "))
                if ind == 0:
                    break
                if base is None:
                    base = ind
                scalar_lines.append(l[base:])
                i += 1
            while scalar_lines and scalar_lines[-1] == "":
                scalar_lines.pop()
            value = "\n".join(scalar_lines)
            if val != "|-":
                if value:
                    value += "\n"
            result[key] = value
            continue

        if val == "":
            # 后续缩进块
            block: List[str] = []
            base = None
            while i < n:
                l = lines[i]
                if l.strip() == "":
                    block.append(l)
                    i += 1
                    continue
                ind = len(l) - len(l.lstrip(" "))
                if ind == 0:
                    break
                if base is None:
                    base = ind
                block.append(l)
                i += 1
            result[key] = _parse_block(block, base)
            continue

        result[key] = _parse_scalar(val)
    return result


def parse_yaml(text: str) -> Dict[str, Any]:
    """解析 YAML 文本：优先 PyYAML，缺失时回退 ``_mini_yaml``。"""
    try:
        import yaml  # type: ignore
    except Exception:
        return _mini_yaml(text) or {}
    data = yaml.safe_load(text)
    return data if isinstance(data, dict) else {}


# --------------------------------------------------------------------------- #
# 加载
# --------------------------------------------------------------------------- #
def _as_list(v: Any) -> List[str]:
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x) for x in v]
    if isinstance(v, str):
        return [x.strip() for x in v.split(",") if x.strip()]
    return [str(v)]


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _account_from_dict(d: Dict[str, Any], name: str, path: Path) -> Account:
    return Account(
        name=str(d.get("name") or name),
        display=str(d.get("display") or ""),
        channel_id=str(d.get("channel_id") or ""),
        client_secrets=str(d.get("client_secrets") or ""),
        token_path=str(d.get("token_path") or ""),
        default_privacy=str(d.get("default_privacy") or "unlisted"),
        default_language=str(d.get("default_language") or "zh"),
        default_category=_as_int(d.get("default_category"), 24),
        default_playlists=_as_list(d.get("default_playlists")),
        tags_pool=_as_list(d.get("tags_pool")),
        title_template=str(d.get("title_template") or ""),
        description_template=str(d.get("description_template") or ""),
        doc_status=str(d.get("doc_status") or "test"),
        daily_publish_cap=_as_int(d.get("daily_publish_cap"), 3),
        extra=d.get("extra") if isinstance(d.get("extra"), dict) else {},
        source_path=str(path),
    )


def list_accounts() -> List[Account]:
    """列出账号根目录下的全部账号（按名字排序）。目录不存在 → 空列表。"""
    base = accounts_dir()
    if not base.is_dir():
        return []
    out: List[Account] = []
    for child in sorted(base.iterdir(), key=lambda p: p.name):
        if not child.is_dir():
            continue
        prof = child / "account.yaml"
        if prof.is_file():
            out.append(load_account(child.name, base=base))
    return out


def load_account(name: str, base: Optional[Path] = None) -> Account:
    """按名字加载账号档案；不存在 → AccountNotFound。"""
    path = account_path(name, base=base)
    if not path.is_file():
        raise AccountNotFound(
            "账号不存在: %s（期望档案: %s）" % (name, path)
        )
    text = path.read_text(encoding="utf-8")
    data = parse_yaml(text)
    if not isinstance(data, dict):
        data = {}
    return _account_from_dict(data, name, path)


def resolve_default() -> Account:
    """解析默认账号：优先 ``$YT_ACCOUNT``，否则名字排序第一个；都没有 → AccountNotFound。"""
    env_name = os.environ.get("YT_ACCOUNT", "").strip()
    if env_name:
        return load_account(env_name)
    accts = list_accounts()
    if not accts:
        raise AccountNotFound(
            "没有可用账号：%s 下未找到任何 account.yaml；"
            "请先 `youtube_accounts.py init <name>`，或设置 YT_ACCOUNT" % accounts_dir()
        )
    return accts[0]


# --------------------------------------------------------------------------- #
# 迁移旧 token
# --------------------------------------------------------------------------- #
def migrate_legacy(target_name: Optional[str] = None, force: bool = False) -> Dict[str, Any]:
    """把旧的 ``$YOUTUBE_DIR/request.token`` 迁移到账号目录并留下兼容软链。

    仅做文件搬迁，账号名由调用方传入（不写死）。幂等：已迁移则直接返回说明。
    ``force=True`` 时会覆盖已存在的目标（旧目标备份为 ``.bak``）。
    """
    if not target_name:
        raise ValueError("migrate_legacy 需要 target_name（账号名）")

    legacy = youtube_dir() / "request.token"
    target = accounts_dir() / target_name / "request.token"
    result: Dict[str, Any] = dict(
        migrated=False,
        reason="",
        legacy=str(legacy),
        target=str(target),
        account=target_name,
        message="",
    )

    # 已是软链且指向目标 → 幂等
    if legacy.is_symlink():
        try:
            if os.path.realpath(str(legacy)) == os.path.realpath(str(target)):
                result["reason"] = "already-migrated"
                result["message"] = "旧 token 已是兼容软链，无需迁移"
                return result
        except OSError:
            pass
        if not force:
            result["reason"] = "legacy-is-symlink"
            result["message"] = "旧 token 是软链但未指向目标，未动（--force 可覆盖）"
            return result

    if not legacy.exists():
        result["reason"] = "no-legacy"
        result["message"] = "未发现旧 token（%s），无需迁移" % legacy
        return result

    if target.exists() and not force:
        result["reason"] = "target-exists"
        result["message"] = "目标 token 已存在（%s），未动；--force 可覆盖" % target
        return result

    target.parent.mkdir(parents=True, exist_ok=True)
    if force and target.exists() and not target.is_symlink():
        shutil.move(str(target), str(target) + ".bak")
        result["backup"] = str(target) + ".bak"

    if legacy.is_symlink() or legacy.is_file():
        shutil.move(str(legacy), str(target))
    else:
        result["reason"] = "legacy-not-file"
        result["message"] = "旧 token 非常规文件，未迁移"
        return result

    rel = os.path.relpath(str(target), str(youtube_dir()))
    os.symlink(rel, str(legacy))
    result["migrated"] = True
    result["reason"] = "migrated"
    result["symlink"] = rel
    result["message"] = "已迁移 %s → %s（并创建软链 %s -> %s）" % (legacy, target, legacy, rel)
    return result


# --------------------------------------------------------------------------- #
# 初始化账号档案
# --------------------------------------------------------------------------- #
def init_account(
    name: str,
    template_values: Optional[Dict[str, Any]] = None,
    target_dir: Optional[Path] = None,
) -> Path:
    """按模板生成 ``<target_dir>/<name>/account.yaml``；已存在则抛 FileExistsError（不覆盖）。"""
    base = Path(target_dir) if target_dir else accounts_dir()
    adir = base / name
    prof = adir / "account.yaml"
    if prof.exists():
        raise FileExistsError("账号档案已存在，未覆盖: %s" % prof)

    values: Dict[str, str] = dict(name=name, display=name)
    for k in ("display", "channel_id", "client_secrets", "token_path",
              "default_privacy", "default_language", "default_category",
              "doc_status", "daily_publish_cap"):
        if template_values and template_values.get(k) is not None:
            values[k] = str(template_values[k])

    tmpl = TEMPLATE_PATH.read_text(encoding="utf-8")
    rendered = string.Template(tmpl).substitute(values)

    adir.mkdir(parents=True, exist_ok=True)
    prof.write_text(rendered, encoding="utf-8")
    return prof
