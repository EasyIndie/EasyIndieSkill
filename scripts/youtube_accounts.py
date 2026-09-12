#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""youtube_accounts.py — 账号管理 CLI（输出 JSON，便于 Hermes 解析）。

用法::

    python3 scripts/youtube_accounts.py list
    python3 scripts/youtube_accounts.py show <name>
    python3 scripts/youtube_accounts.py init <name> [--display D] [--channel-id ID]
    python3 scripts/youtube_accounts.py migrate [--target-name NAME] [--yes] [--force]

``migrate`` 默认只打印迁移计划（dry-run）；``--yes`` 才真正搬迁旧 token。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import ytauto_accounts as A  # noqa: E402


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _plan_migrate(target_name, force=False):
    legacy = A.youtube_dir() / "request.token"
    target = A.accounts_dir() / target_name / "request.token"
    plan = dict(
        target_name=target_name, legacy=str(legacy), target=str(target),
        legacy_exists=legacy.exists(), legacy_is_symlink=legacy.is_symlink(),
        target_exists=target.exists(), force=force,
    )
    if legacy.is_symlink() and os.path.realpath(str(legacy)) == os.path.realpath(str(target)):
        plan["action"] = "noop"
        plan["reason"] = "already-migrated"
    elif not legacy.exists():
        plan["action"] = "noop"
        plan["reason"] = "no-legacy"
    elif target.exists() and not force:
        plan["action"] = "noop"
        plan["reason"] = "target-exists"
    else:
        plan["action"] = "migrate"
        plan["reason"] = "ready"
    return plan


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ytauto 账号管理")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    sub.add_parser("list", help="列出全部账号")

    sp = sub.add_parser("show", help="显示单个账号档案")
    sp.add_argument("name")

    sp = sub.add_parser("init", help="生成账号档案（不覆盖）")
    sp.add_argument("name")
    sp.add_argument("--display")
    sp.add_argument("--channel-id")
    sp.add_argument("--client-secrets")
    sp.add_argument("--target-dir")

    sp = sub.add_parser("migrate", help="迁移旧 request.token 到账号目录")
    sp.add_argument("--target-name")
    sp.add_argument("--yes", action="store_true", help="真正执行（默认只 dry-run）")
    sp.add_argument("--force", action="store_true")

    args = p.parse_args(argv)

    if args.cmd == "list":
        _out(dict(ok=True, accounts_dir=str(A.accounts_dir()),
                  accounts=[a.to_dict() for a in A.list_accounts()]))
        return 0

    if args.cmd == "show":
        try:
            acct = A.load_account(args.name)
        except A.AccountNotFound as e:
            _out(dict(ok=False, error=str(e)))
            return 1
        _out(dict(ok=True, account=acct.to_dict()))
        return 0

    if args.cmd == "init":
        values = dict(display=args.display, channel_id=args.channel_id,
                      client_secrets=args.client_secrets)
        target_dir = Path(args.target_dir) if args.target_dir else None
        try:
            path = A.init_account(args.name, template_values=values, target_dir=target_dir)
        except FileExistsError as e:
            _out(dict(ok=False, error=str(e)))
            return 1
        _out(dict(ok=True, created=str(path), account=args.name))
        return 0

    if args.cmd == "migrate":
        target_name = args.target_name or os.environ.get("YT_ACCOUNT") or "amazing-archive"
        if not args.yes:
            plan = _plan_migrate(target_name, force=args.force)
            _out(dict(ok=True, dry_run=True, plan=plan,
                      hint="加 --yes 才真正搬迁"))
            return 0
        try:
            res = A.migrate_legacy(target_name=target_name, force=args.force)
        except ValueError as e:
            _out(dict(ok=False, error=str(e)))
            return 1
        _out(dict(ok=True, dry_run=False, result=res))
        return 0

    _out(dict(ok=False, error="未知子命令: %s" % args.cmd))
    return 2


if __name__ == "__main__":
    sys.exit(main())
