#!/usr/bin/env python3
"""把通過驗證的 data subject 晉升到正式區。

用法（在專案根目錄）：
    python promote.py <名> [--domain DOM] [--update]

前提與行為：
  1. reports/<名>.report.json 必須存在且 summary.compliant 為 true
     （先跑 python run.py，不合規的 subject 不能晉升）。
  2. 從 input/ 搬三件到 production/<DOM>/<名>/：
       <名>.sql、<名>.relations.yaml、<名>.context.md
     （樣本不進正式區——樣本是驗證當下的證據，不是正式資產；
       晉升記錄改存各 CSV 的 SHA256 供追溯。）
  3. 寫入 _promotion.yaml 晉升記錄：
       promoted_at        晉升時間
       gate_result_code   卡控結果碼 = 閘門區 findings（rule|status|target）排序後的 SHA256
       rule_version_code  規則版本碼 = build/compiled_rules.json 內容的 SHA256
       sample_hashes      各樣本 CSV 的 SHA256
     兩碼與雙碼因果保證接軌：之後規則演進時，production_audit.py
     可機械判斷哪些 subject 是用舊規則通過的、需要重驗。
  4. 目標資料夾已存在時拒絕，除非 --update（會在記錄中保留前一版晉升資訊）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone

import yaml

from dataval.precheck import parse_context, locate_pieces
from dataval.prodgraph import current_rule_code
from dataval import report_paths

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.environ.get("DATAVAL_INPUT_DIR", os.path.join(HERE, "input"))
REPORT_DIR = os.environ.get("DATAVAL_REPORT_DIR", os.path.join(HERE, "reports"))
PRODUCTION_ROOT = os.environ.get(
    "DATAVAL_PRODUCTION_DIR", os.path.join(HERE, "production"))
COMPILED = os.path.join(HERE, "build", "compiled_rules.json")


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def gate_result_code(report: dict) -> str:
    """卡控結果碼：閘門區每筆 finding 的 (rule|status|target) 排序後雜湊。"""
    rows = sorted(
        f"{f.get('check_id')}|{f.get('status')}|{f.get('target')}"
        for f in report.get("findings", [])
        if f.get("zone") == "gating")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()[:16]


def fail(msg: str):
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="data subject 名（input/<名>.sql）")
    ap.add_argument("--domain", help="目標 domain；context 只宣告一個時可省略")
    ap.add_argument("--update", action="store_true",
                    help="目標已存在時覆蓋並保留前版晉升記錄")
    args = ap.parse_args()
    name = args.name

    # ── ① 三件輸入必須齊全（標準：input/<名>/；平鋪相容） ──
    ddl_path = os.path.join(INPUT_DIR, name, f"{name}.sql")
    if not os.path.isfile(ddl_path):
        ddl_path = os.path.join(INPUT_DIR, f"{name}.sql")
    located = locate_pieces(ddl_path)
    pieces = {"sql": ddl_path,
              "relations": located["relations"],
              "context": located["context"]}
    for label, path in pieces.items():
        if not os.path.isfile(path):
            fail(f"缺 {os.path.relpath(path, HERE)}；四件輸入契約見 input/README.md")

    # ── ② 最新報告必須合規 ─────────────────────────────
    # 報告可能已依 domain 分類到 reports/<域>/，用 helper 定位（相容扁平舊路徑）。
    report_path = report_paths.find_report_json(REPORT_DIR, name)
    if report_path is None:
        fail(f"找不到 {name}.report.json（reports/ 或其分類子夾）；請先跑 python run.py")
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    if not report.get("summary", {}).get("compliant"):
        blocked = report.get("blocking_summary", {}).get("blocked", [])
        rules = "、".join(b.get("rule", "?") for b in blocked) or "(未知)"
        fail(f"{name} 不合規（卡下來的規則：{rules}），不能晉升。")
    if not os.path.isfile(COMPILED):
        fail("找不到 build/compiled_rules.json；請先跑 python run.py")

    # ── ③ 決定 domain ─────────────────────────────────
    with open(pieces["context"], encoding="utf-8") as f:
        meta, _ = parse_context(f.read())
    declared = [str(d) for d in (meta.get("domains") or [])]
    domain = args.domain
    if domain is None:
        if len(declared) == 1:
            domain = declared[0]
        elif not declared:
            fail("context.md 未宣告 domains；請用 --domain 指定目標 domain。")
        else:
            fail(f"context.md 宣告了多個 domain {declared}；請用 --domain 指定其一。")
    elif declared and domain not in declared:
        fail(f"--domain {domain} 不在 context.md 宣告的 {declared} 內。")

    # ── ④ 搬移與晉升記錄 ───────────────────────────────
    dest = os.path.join(PRODUCTION_ROOT, domain, name)
    previous = None
    if os.path.isdir(dest):
        if not args.update:
            fail(f"{os.path.relpath(dest, HERE)} 已存在；重新晉升請加 --update。")
        prev_path = os.path.join(dest, "_promotion.yaml")
        if os.path.isfile(prev_path):
            with open(prev_path, encoding="utf-8") as f:
                previous = yaml.safe_load(f) or {}
        shutil.rmtree(dest)
    os.makedirs(dest)
    dest_names = {"sql": f"{name}.sql",
                  "relations": f"{name}.relations.yaml",
                  "context": f"{name}.context.md"}
    for label, src in pieces.items():
        shutil.copy2(src, os.path.join(dest, dest_names[label]))

    samples_dir = located["samples"]
    sample_hashes = {}
    if os.path.isdir(samples_dir):
        for fn in sorted(os.listdir(samples_dir)):
            if fn.lower().endswith(".csv"):
                sample_hashes[fn] = sha256_file(os.path.join(samples_dir, fn))

    record = {
        "subject": name,
        "domain": domain,
        "promoted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gate_result_code": gate_result_code(report),
        "rule_version_code": current_rule_code(COMPILED),
        "report_generated_at": report.get("generated_at", ""),
        "sample_hashes": sample_hashes,
    }
    if previous:
        record["previous"] = {
            "promoted_at": previous.get("promoted_at"),
            "gate_result_code": previous.get("gate_result_code"),
            "rule_version_code": previous.get("rule_version_code"),
        }
    with open(os.path.join(dest, "_promotion.yaml"), "w", encoding="utf-8") as f:
        yaml.safe_dump(record, f, allow_unicode=True, sort_keys=False)

    rel = os.path.relpath(dest, HERE)
    print(f"✅ {name} 已晉升到 {rel}/")
    print(f"   卡控結果碼 {record['gate_result_code']}"
          f" ｜ 規則版本碼 {record['rule_version_code']}")
    print("   （樣本未搬入正式區；晉升記錄已存各 CSV 的 SHA256。）")


if __name__ == "__main__":
    main()
