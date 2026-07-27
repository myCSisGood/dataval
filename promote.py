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
       gate_result_code   卡控結果碼 = 閘門 findings 的決策欄位 SHA256
       rule_version_code  驗證 bundle = 規則＋Python／內建 validator＋依賴版本 SHA256
       input_hashes       四件輸入各檔 SHA256
     兩碼與雙碼因果保證接軌：之後規則演進時，production_audit.py
     可機械判斷哪些 subject 是用舊規則通過的、需要重驗。
  4. 目標資料夾已存在時拒絕，除非 --update（會在記錄中保留前一版晉升資訊）。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone

import yaml

from dataval.precheck import parse_context, locate_pieces
from dataval.compiler import require_current_compiled
from dataval.provenance import (
    manifest_mismatches,
    sha256_file,
    validation_manifest,
)

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.environ.get("DATAVAL_INPUT_DIR", os.path.join(HERE, "input"))
REPORT_DIR = os.environ.get("DATAVAL_REPORT_DIR", os.path.join(HERE, "reports"))
PRODUCTION_ROOT = os.environ.get(
    "DATAVAL_PRODUCTION_DIR", os.path.join(HERE, "production"))
COMPILED = os.path.join(HERE, "build", "compiled_rules.json")
DOMAIN_ROOT = os.path.join(HERE, "config")
RULES_ROOT = os.path.join(HERE, "config", "Common", "knowhow_py")


def gate_result_code(report: dict) -> str:
    """卡控結果碼：閘門 finding 的決策欄位排序後雜湊。"""
    rows = sorted(
        f"{f.get('check_id')}|{f.get('status')}|{f.get('severity')}|{f.get('target')}"
        for f in report.get("findings", [])
        if f.get("zone") == "gating")
    return hashlib.sha256("\n".join(rows).encode("utf-8")).hexdigest()[:16]


def fail(msg: str):
    print(f"❌ {msg}", file=sys.stderr)
    sys.exit(1)


def _safe_slug(value: str, label: str) -> str:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", value or ""):
        fail(f"{label} 只能包含英數、底線或連字號，且必須以英文字母開頭：{value!r}")
    return value


def _inside(root: str, path: str) -> bool:
    try:
        return os.path.commonpath(
            [os.path.realpath(root), os.path.realpath(path)]) == os.path.realpath(root)
    except ValueError:
        return False


def _install_atomically(staging: str, dest: str, *, update: bool):
    """Install a staged subject with rollback if replacement fails."""
    if not os.path.exists(dest):
        os.replace(staging, dest)
        return
    if not update:
        fail(f"{os.path.relpath(dest, HERE)} 已存在；重新晉升請加 --update。")
    backup = tempfile.mkdtemp(prefix=f".{os.path.basename(dest)}.backup-",
                              dir=os.path.dirname(dest))
    os.rmdir(backup)
    os.replace(dest, backup)
    try:
        os.replace(staging, dest)
    except Exception:
        os.replace(backup, dest)
        raise
    try:
        shutil.rmtree(backup)
    except OSError as error:
        print(f"⚠️ 新版已完成晉升，但舊版暫存 {backup} 清理失敗：{error}",
              file=sys.stderr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", help="data subject 名（input/<名>/<名>.sql）")
    ap.add_argument("--domain", help="目標 domain；context 只宣告一個時可省略")
    ap.add_argument("--update", action="store_true",
                    help="目標已存在時覆蓋並保留前版晉升記錄")
    args = ap.parse_args()
    name = _safe_slug(args.name, "data subject 名")

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
    if not os.path.isdir(located["samples"]):
        fail(f"缺 {os.path.relpath(located['samples'], HERE)}/；"
             "四件輸入契約見 input/README.md")

    # ── ② 最新報告必須合規 ─────────────────────────────
    report_path = os.path.join(REPORT_DIR, f"{name}.report.json")
    if not os.path.isfile(report_path):
        fail(f"找不到 {os.path.relpath(report_path, HERE)}；請先跑 python run.py")
    with open(report_path, encoding="utf-8") as f:
        report = json.load(f)
    if not report.get("summary", {}).get("compliant"):
        blocked = report.get("blocking_summary", {}).get("blocked", [])
        rules = "、".join(b.get("rule", "?") for b in blocked) or "(未知)"
        fail(f"{name} 不合規（卡下來的規則：{rules}），不能晉升。")
    try:
        require_current_compiled(DOMAIN_ROOT, RULES_ROOT, COMPILED)
    except Exception as error:
        fail(f"目前規則 bundle 無法編譯：{type(error).__name__}: {error}")

    current_manifest = validation_manifest(ddl_path, COMPILED)
    expected_manifest = (report.get("meta") or {}).get("validation_manifest")
    provenance_errors = manifest_mismatches(expected_manifest, current_manifest)
    if provenance_errors:
        fail("報告與目前輸入／驗證 bundle 不一致，請重新執行 python run.py：\n  - "
             + "\n  - ".join(provenance_errors))

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
    domain = _safe_slug(str(domain), "domain")

    # ── ④ 搬移與晉升記錄 ───────────────────────────────
    dest = os.path.join(PRODUCTION_ROOT, domain, name)
    if not _inside(PRODUCTION_ROOT, dest):
        fail("晉升目標超出 production 根目錄，已拒絕。")
    previous = None
    if os.path.isdir(dest):
        if not args.update:
            fail(f"{os.path.relpath(dest, HERE)} 已存在；重新晉升請加 --update。")
        prev_path = os.path.join(dest, "_promotion.yaml")
        if os.path.isfile(prev_path):
            with open(prev_path, encoding="utf-8") as f:
                previous = yaml.safe_load(f) or {}
    domain_dir = os.path.dirname(dest)
    os.makedirs(domain_dir, exist_ok=True)
    staging = tempfile.mkdtemp(prefix=f".{name}.staging-", dir=domain_dir)
    dest_names = {"sql": f"{name}.sql",
                  "relations": f"{name}.relations.yaml",
                  "context": f"{name}.context.md"}
    for label, src in pieces.items():
        shutil.copy2(src, os.path.join(staging, dest_names[label]))

    samples_dir = located["samples"]
    sample_hashes = {}
    if os.path.isdir(samples_dir):
        for fn in sorted(os.listdir(samples_dir)):
            if fn.lower().endswith(".csv"):
                sample_hashes[fn] = sha256_file(
                    os.path.join(samples_dir, fn), length=16)

    record = {
        "subject": name,
        "domain": domain,
        "promoted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "gate_result_code": gate_result_code(report),
        "rule_version_code": current_manifest["validation_bundle_code"],
        "validation_manifest": current_manifest,
        "input_hashes": current_manifest["input_hashes"],
        "report_generated_at": report.get("generated_at", ""),
        "sample_hashes": sample_hashes,
    }
    if previous:
        record["previous"] = {
            "promoted_at": previous.get("promoted_at"),
            "gate_result_code": previous.get("gate_result_code"),
            "rule_version_code": previous.get("rule_version_code"),
        }
    try:
        with open(os.path.join(staging, "_promotion.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump(record, f, allow_unicode=True, sort_keys=False)
        _install_atomically(staging, dest, update=args.update)
    except Exception as error:
        if os.path.isdir(staging):
            shutil.rmtree(staging)
        fail(f"晉升寫入失敗，原正式資產已保留：{type(error).__name__}: {error}")

    rel = os.path.relpath(dest, HERE)
    print(f"✅ {name} 已晉升到 {rel}/")
    print(f"   卡控結果碼 {record['gate_result_code']}"
          f" ｜ 規則版本碼 {record['rule_version_code']}")
    print("   （樣本未搬入正式區；晉升記錄已存各 CSV 的 SHA256。）")


if __name__ == "__main__":
    main()
