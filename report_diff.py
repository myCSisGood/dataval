#!/usr/bin/env python3
"""比對兩份 report.json，列出 findings 的新增／消失／狀態改變。

    python report_diff.py <舊.report.json> <新.report.json>

用途：改了規則或改了 DDL 後，想知道「這次跟上次比，多了哪些違規、少了哪些、
哪些從 pass 變 fail」。以 (check_id, target) 對齊逐筆比對，忽略時間戳。
純只讀，不改任何檔案。
"""
from __future__ import annotations
import argparse
import json
import os
import sys

from dataval.report import diff_findings

_STATUS_ICON = {"pass": "✅", "warning": "⚠️", "fail": "❌", "info": "ℹ️",
                "skipped": "⏭️"}


def _load(path: str) -> dict:
    if not os.path.isfile(path):
        sys.exit(f"找不到檔案：{path}")
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        sys.exit(f"讀取 {path} 失敗：{type(e).__name__}: {e}")


def _icon(status: str) -> str:
    return _STATUS_ICON.get(status, "·")


def main():
    ap = argparse.ArgumentParser(description="比對兩份 report.json 的 findings")
    ap.add_argument("old", help="舊的 report.json")
    ap.add_argument("new", help="新的 report.json")
    args = ap.parse_args()

    old, new = _load(args.old), _load(args.new)
    d = diff_findings(old, new)
    added, removed, changed = d["added"], d["removed"], d["changed"]

    print(f"比對：{os.path.relpath(args.old)} → {os.path.relpath(args.new)}")
    print(f"新增 {len(added)} 筆 ｜ 消失 {len(removed)} 筆 ｜ 狀態或訊息改變 {len(changed)} 筆")
    print()

    if added:
        print(f"➕ 新增（新報告才有）{len(added)} 筆：")
        for f in added:
            print(f"   {_icon(f['status'])} {f['check_id']} @ {f['target']}"
                  f" — {f['message']}")
        print()
    if removed:
        print(f"➖ 消失（舊報告才有）{len(removed)} 筆：")
        for f in removed:
            print(f"   {_icon(f['status'])} {f['check_id']} @ {f['target']}"
                  f" — {f['message']}")
        print()
    if changed:
        print(f"✏️ 改變（同一 check_id＋對象）{len(changed)} 筆：")
        for f in changed:
            print(f"   {f['check_id']} @ {f['target']}")
            for field, fromto in f["fields"].items():
                if field == "status":
                    print(f"      狀態：{_icon(fromto['from'])} {fromto['from']}"
                          f" → {_icon(fromto['to'])} {fromto['to']}")
                else:
                    print(f"      {field}：{fromto['from']!r} → {fromto['to']!r}")
        print()

    if not (added or removed or changed):
        print("兩份報告的 findings 完全一致（僅時間戳可能不同）。")


if __name__ == "__main__":
    main()
