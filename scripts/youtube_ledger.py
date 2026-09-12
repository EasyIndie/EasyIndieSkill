#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""youtube_ledger.py — 上传台账 CLI（输出 JSON）。

用法::

    python3 scripts/youtube_ledger.py show [--account X] [--limit 20]
    python3 scripts/youtube_ledger.py find --source-url U | --video-id V
    python3 scripts/youtube_ledger.py count-today --account X
    python3 scripts/youtube_ledger.py summary [--days 30] [--account X]
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from lib import ytauto_ledger as L  # noqa: E402


def _out(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="ytauto 上传台账")
    sub = p.add_subparsers(dest="cmd")
    sub.required = True

    sp = sub.add_parser("show")
    sp.add_argument("--account")
    sp.add_argument("--limit", type=int, default=20)

    sp = sub.add_parser("find")
    sp.add_argument("--source-url")
    sp.add_argument("--video-id")

    sp = sub.add_parser("count-today")
    sp.add_argument("--account", required=True)

    sp = sub.add_parser("summary")
    sp.add_argument("--days", type=int, default=30)
    sp.add_argument("--account")

    args = p.parse_args(argv)

    if args.cmd == "show":
        rows = [r for r in L.iter_rows()
                if not args.account or r.get("account") == args.account]
        if args.limit and args.limit > 0:
            rows = rows[-args.limit:]
        _out(dict(ok=True, ledger=str(L.ledger_path()), count=len(rows), rows=rows))
        return 0

    if args.cmd == "find":
        if not args.source_url and not args.video_id:
            _out(dict(ok=False, error="需提供 --source-url 或 --video-id"))
            return 2
        rows = L.find(source_url=args.source_url, video_id=args.video_id)
        _out(dict(ok=True, count=len(rows), rows=rows))
        return 0

    if args.cmd == "count-today":
        _out(dict(ok=True, account=args.account,
                  count=L.count_today(args.account)))
        return 0

    if args.cmd == "summary":
        _out(dict(ok=True, **L.summary(account=args.account, days=args.days)))
        return 0

    _out(dict(ok=False, error="未知子命令: %s" % args.cmd))
    return 2


if __name__ == "__main__":
    sys.exit(main())
