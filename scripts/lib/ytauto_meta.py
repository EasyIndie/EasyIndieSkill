#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ytauto_meta.py — youtubeuploader ``-metaJSON`` 构造与校验。

优先级：显式参数 > 账号档案默认 > 内置默认。

``build_meta()`` 返回 ``MetaResult``（``dict`` 子类），可直接
``json.dump`` 为 metaJSON；同时把提示信息挂在 ``.warnings`` 上，
把封面/字幕路径挂在 ``.thumbnail`` / ``.caption``（它们不是 metaJSON 字段，
由上传 CLI 通过 ``-thumbnail`` / ``-caption`` 传参）。

metaJSON 字段：title / description / tags / categoryId / privacyStatus /
publishAt / playlistTitles / playlistIds / language / 以及 extra 透传字段。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = [
    "MetaError",
    "MetaResult",
    "build_meta",
    "validate_meta",
    "validate_go_meta_types",
    "dump_meta",
]

# --- youtubeuploader VideoMeta 类型契约 ------------------------------------ #
# 见 porjo/youtubeuploader http.go：
#   type VideoMeta struct {
#       Title, Description, CategoryId string
#       Tags []string
#       PrivacyStatus, Embeddable, License string
#       PublicStatsViewable *bool
#       PublishAt Date            // time.Time（RFC3339）
#       MadeForKids bool
#       ContainsSyntheticMedia bool
#       RecordingDate Date
#       PlaylistIDs, PlaylistTitles []string
#       Language string
#       Localizations map[string]youtube.VideoLocalization
#   }
_GO_STR_FIELDS = ("title", "description", "categoryId", "privacyStatus",
                  "license", "language")
_GO_STR_LIST_FIELDS = ("tags", "playlistIds", "playlistTitles")
_GO_BOOL_FIELDS = ("embeddable", "publicStatsViewable", "madeForKids",
                   "containsSyntheticMedia")
_GO_DATE_FIELDS = ("publishAt", "recordingDate")

CATEGORY_MIN = 1
CATEGORY_MAX = 44

VALID_PRIVACY = ("public", "unlisted", "private")
MAX_TAGS = 15
MAX_TAG_LEN = 30
MAX_TAGS_CHARS = 450
_PLAYLIST_RE = re.compile(r"^(?:PL|UU|OL|FL|LL)[A-Za-z0-9_-]{10,}$")
_GENERIC_ID_RE = re.compile(r"^[A-Za-z0-9_-]{24,}$")


class MetaError(Exception):
    """metaJSON 构造/校验失败。"""


class MetaResult(dict):
    """metaJSON dict 子类，附带 warnings / thumbnail / caption。"""

    def __init__(self, *args, **kwargs):
        warnings = kwargs.pop("warnings", None)
        thumbnail = kwargs.pop("thumbnail", None)
        caption = kwargs.pop("caption", None)
        super().__init__(*args, **kwargs)
        self.warnings: List[str] = warnings if warnings is not None else []
        self.thumbnail = thumbnail
        self.caption = caption

    def to_json(self, **kw) -> str:
        return json.dumps(self, ensure_ascii=False, indent=2, **kw)


def _norm_tags(*groups: Any) -> List[str]:
    """合并 + 去重保序 + 丢弃空/超长 + 数量与总字符截断。"""
    seen = set()
    out: List[str] = []
    total = 0
    for group in groups:
        if group is None:
            continue
        if isinstance(group, str):
            group = [x for x in group.split(",")]
        for raw in group:
            t = str(raw).strip()
            if not t:
                continue
            if len(t) > MAX_TAG_LEN:
                continue
            low = t.lower()
            if low in seen:
                continue
            if len(out) >= MAX_TAGS:
                break
            if total + len(t) > MAX_TAGS_CHARS:
                break
            seen.add(low)
            out.append(t)
            total += len(t)
    return out


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def _render(template: str, values: Dict[str, Any]) -> str:
    safe = _SafeDict()
    for k, v in values.items():
        safe[k] = "" if v is None else str(v)
    try:
        return template.format_map(safe)
    except (ValueError, KeyError, IndexError):
        return template


def _norm_category_id(value: Any) -> str:
    """把 categoryId 规范为字符串（youtubeuploader Go 结构体要求 string）。

    接受 int / 纯数字字符串 / 整数值 float；非法类型或非数字 → MetaError。
    取值范围（1-44）由 ``validate_meta`` 校验。
    """
    if isinstance(value, bool):
        raise MetaError("categoryId 非法（布尔值）: %r" % (value,))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str):
        s = value.strip()
        if not s.isdigit():
            raise MetaError(
                "categoryId 必须是 1-44 的整数（youtubeuploader 要求字符串，"
                "如 \"24\"）: %r" % (value,))
        return s
    if isinstance(value, float):
        if not value.is_integer():
            raise MetaError("categoryId 必须是整数: %r" % (value,))
        return str(int(value))
    raise MetaError(
        "categoryId 类型非法（须为 int 或数字字符串，youtubeuploader 要求字符串）: %r"
        % (value,))


def parse_publish_at(value: str) -> datetime:
    """解析 ISO8601（容忍结尾 ``Z``），要求带时区且为未来时间。"""
    raw = str(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise MetaError("publishAt 不是合法 ISO8601: %s" % value)
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise MetaError("publishAt 必须带时区（如 2026-01-01T00:00:00+08:00）: %s" % value)
    if dt <= datetime.now(timezone.utc):
        raise MetaError("publishAt 必须是未来时间: %s" % value)
    return dt


def build_meta(
    account: Any,
    *,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Any = None,
    source_tags: Any = None,
    playlists: Any = None,
    playlist_ids: Any = None,
    privacy: Optional[str] = None,
    publish_at: Optional[str] = None,
    category_id: Any = None,
    language: Optional[str] = None,
    thumbnail: Optional[str] = None,
    caption: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    summary: Optional[str] = None,
    hook: Optional[str] = None,
    keywords: Any = None,
) -> MetaResult:
    """构造 metaJSON（dict）。标题为空 → MetaError。"""
    warnings: List[str] = []

    # --- 文案模板渲染 --------------------------------------------------- #
    merged_tags = _norm_tags(getattr(account, "tags_pool", None), source_tags, tags)
    values = dict(
        hook=hook,
        summary=summary,
        keywords=keywords if isinstance(keywords, str) else (
            ", ".join(keywords) if keywords else ""),
        tags=", ".join(merged_tags),
    )

    resolved_title = title
    if not resolved_title and getattr(account, "title_template", ""):
        resolved_title = _render(account.title_template, values)
    resolved_title = (resolved_title or "").strip()
    if not resolved_title:
        raise MetaError("title 必填（显式 --title 或账号 title_template 至少给一个）")

    if description is not None and str(description).strip() != "":
        resolved_desc = str(description).strip()
    elif getattr(account, "description_template", ""):
        resolved_desc = _render(account.description_template, values).strip()
    else:
        resolved_desc = ""

    # --- 默认值 --------------------------------------------------------- #
    resolved_privacy = (privacy or getattr(account, "default_privacy", "") or "unlisted")
    resolved_lang = (language or getattr(account, "default_language", "") or "zh")
    if category_id is not None:
        resolved_category = _norm_category_id(category_id)
    elif getattr(account, "default_category", None) is not None:
        resolved_category = _norm_category_id(account.default_category)
    else:
        resolved_category = "24"

    if playlists:
        resolved_playlists = [str(x) for x in playlists]
    else:
        resolved_playlists = [str(x) for x in getattr(account, "default_playlists", []) or []]
    resolved_playlist_ids = [str(x) for x in (playlist_ids or [])]

    meta = MetaResult(warnings=warnings, thumbnail=thumbnail, caption=caption)

    # --- publishAt / privacy 联动 --------------------------------------- #
    if publish_at:
        parse_publish_at(publish_at)  # 校验（未来 + 带时区）
        if resolved_privacy != "private":
            warnings.append(
                "publishAt 已设置 → privacyStatus 自动由 %s 改为 private（计划发布必须 private）"
                % resolved_privacy
            )
            resolved_privacy = "private"
        meta["publishAt"] = str(publish_at).strip()

    # --- 只写非空字段 --------------------------------------------------- #
    meta["title"] = resolved_title
    if resolved_desc:
        meta["description"] = resolved_desc
    if merged_tags:
        meta["tags"] = merged_tags
    if resolved_category:
        meta["categoryId"] = resolved_category
    if resolved_privacy:
        meta["privacyStatus"] = resolved_privacy
    if resolved_playlists:
        meta["playlistTitles"] = resolved_playlists
    if resolved_playlist_ids:
        meta["playlistIds"] = resolved_playlist_ids
    if resolved_lang:
        meta["language"] = resolved_lang

    # --- extra 透传（账号档案 → 显式参数，显式优先） --------------------- #
    for src in (getattr(account, "extra", None), extra):
        if isinstance(src, dict):
            for k, v in src.items():
                if v is None or v == "" or v == [] or v == {}:
                    continue
                meta[k] = v

    # 最后一道闸门：业务校验 + 与 youtubeuploader Go 结构体的类型契约
    errors = validate_meta(meta)
    errors += validate_go_meta_types(meta)
    if errors:
        raise MetaError("meta 校验失败: " + "; ".join(errors))
    return meta


def validate_meta(meta: Dict[str, Any]) -> List[str]:
    """返回错误列表（空列表 = 通过）。"""
    errors: List[str] = []
    title = meta.get("title", "")
    if not title:
        errors.append("title 缺失")
    elif len(str(title)) > 100:
        errors.append("title 超过 100 字符")

    desc = meta.get("description", "")
    if desc and len(str(desc)) > 5000:
        errors.append("description 超过 5000 字符")

    privacy = meta.get("privacyStatus")
    if privacy is not None and privacy not in VALID_PRIVACY:
        errors.append("privacyStatus 非法: %r（须为 public/unlisted/private）" % privacy)

    if "categoryId" in meta:
        cid = meta["categoryId"]
        valid = False
        if isinstance(cid, bool):
            valid = False
        elif isinstance(cid, int):
            valid = CATEGORY_MIN <= cid <= CATEGORY_MAX
        elif isinstance(cid, str) and cid.strip().isdigit():
            valid = CATEGORY_MIN <= int(cid.strip()) <= CATEGORY_MAX
        if not valid:
            errors.append(
                "categoryId 必须是 %d-%d 的整数（youtubeuploader 要求字符串，"
                "如 \"24\"）: %r" % (CATEGORY_MIN, CATEGORY_MAX, cid))

    if meta.get("publishAt"):
        try:
            parse_publish_at(meta["publishAt"])
        except MetaError as e:
            errors.append(str(e))
        if meta.get("privacyStatus") != "private":
            errors.append("设置 publishAt 时 privacyStatus 必须为 private")

    for pid in meta.get("playlistIds", []) or []:
        s = str(pid)
        if not (_PLAYLIST_RE.match(s) or _GENERIC_ID_RE.match(s)):
            errors.append("playlistId 格式可疑: %s" % s)
    return errors


def validate_go_meta_types(meta: Dict[str, Any]) -> List[str]:
    """逐字段断言 metaJSON 与 youtubeuploader ``VideoMeta`` 的 Go 类型一致。

    返回错误描述列表（空列表 = 全部通过）。只校验出现的字段；布尔与
    Date 字段是可选的。
    """
    errors: List[str] = []
    for field in _GO_STR_FIELDS:
        if field in meta and not isinstance(meta[field], str):
            errors.append(
                "%s 必须是字符串（Go string），实际为 %s"
                % (field, type(meta[field]).__name__))
    for field in _GO_STR_LIST_FIELDS:
        if field not in meta:
            continue
        value = meta[field]
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            errors.append(
                "%s 必须是字符串数组（Go []string），实际为 %s"
                % (field, type(value).__name__))
    for field in _GO_BOOL_FIELDS:
        if field in meta and not isinstance(meta[field], bool):
            errors.append(
                "%s 必须是布尔值（Go bool/*bool），实际为 %s"
                % (field, type(meta[field]).__name__))
    for field in _GO_DATE_FIELDS:
        if field in meta and not isinstance(meta[field], str):
            errors.append(
                "%s 必须是 RFC3339 字符串（Go Date），实际为 %s"
                % (field, type(meta[field]).__name__))
    return errors


def dump_meta(meta: Dict[str, Any], path: Any) -> Path:
    """写 metaJSON 到文件（UTF-8 / ensure_ascii=False / 缩进 2）。"""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
        f.write("\n")
    return p
