#!/usr/bin/env python3
"""正式區全區健檢。

用法（在專案根目錄）：
    python production_audit.py

檢查整個 production/（不是驗新 subject，是掃既有資產）：
  - 每個 subject 三件齊全（DDL / relations / context）、DDL 可解析
  - 舊式平鋪 DDL 提醒遷移（warn）
  - 斷鏈：關聯指向的上游表不存在於正式區任何 subject（fail）
  - 全域循環：subject 之間的關聯圖出現循環（fail）
  - 基數矛盾：同一對端點在不同 subject 有不同 cardinality 宣告（fail）
  - 規則版本碼 drift：晉升時的規則版本 ≠ 現行版本 → 建議重驗（warn）

輸出 console 摘要與 reports/production_audit.md；有 fail 時 exit code 1。
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from dataval.compiler import require_current_compiled
from dataval.prodgraph import audit, current_rule_code

HERE = os.path.dirname(os.path.abspath(__file__))
PRODUCTION_ROOT = os.environ.get(
    "DATAVAL_PRODUCTION_DIR", os.path.join(HERE, "production"))
REPORT_DIR = os.environ.get("DATAVAL_REPORT_DIR", os.path.join(HERE, "reports"))
DOMAIN_ROOT = os.path.join(HERE, "config")
RULES_ROOT = os.path.join(HERE, "config", "Common", "knowhow_py")

ICON = {"fail": "❌", "warn": "⚠️", "ok": "✅"}


def main():
    try:
        compiled_path = require_current_compiled(
            DOMAIN_ROOT, RULES_ROOT,
            os.path.join(HERE, "build", "compiled_rules.json"))
    except Exception as error:
        print(f"❌ 驗證 bundle 尚未就緒：{error}", file=sys.stderr)
        print("請先執行 run.py，讓規則變更被編譯並記入 rules_history。",
              file=sys.stderr)
        sys.exit(1)
    rule_code = current_rule_code(compiled_path)
    result = audit(PRODUCTION_ROOT, rule_code)
    subjects, rows = result["subjects"], result["rows"]

    print(f"正式區健檢：{len(subjects)} 個 subject ｜ 現行規則版本碼 {rule_code}")
    for s in subjects:
        tag = "（legacy 平鋪）" if s.legacy else ""
        code = (s.promotion or {}).get("rule_version_code", "—")
        print(f"  • {s.domain}/{s.name}{tag}"
              f" ｜ 表 {len(s.tables)} ｜ 關聯 {len(s.relations)}"
              f" ｜ 晉升規則版本碼 {code}")
    if rows:
        print("發現事項：")
        for level, target, message in rows:
            print(f"  {ICON[level]} {target}：{message}")
    else:
        print("  ✅ 全區無發現事項。")

    os.makedirs(REPORT_DIR, exist_ok=True)
    md_path = os.path.join(REPORT_DIR, "production_audit.md")
    with open(md_path, "w", encoding="utf-8") as f:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        f.write(f"# 正式區健檢報告\n\n_產生時間 {now}_ ｜ "
                f"現行規則版本碼 `{rule_code}`\n\n")
        f.write("## Subject 清單\n\n")
        f.write("| Subject | 表 | 關聯 | 晉升時間 | 晉升規則版本碼 |\n|---|---|---|---|---|\n")
        for s in subjects:
            p = s.promotion or {}
            name = f"{s.domain}/{s.name}" + ("（legacy）" if s.legacy else "")
            f.write(f"| {name} | {len(s.tables)} | {len(s.relations)} "
                    f"| {p.get('promoted_at', '—')} "
                    f"| `{p.get('rule_version_code', '—')}` |\n")
        f.write("\n## 發現事項\n\n")
        if rows:
            f.write("| 等級 | 對象 | 說明 |\n|---|---|---|\n")
            for level, target, message in rows:
                f.write(f"| {ICON[level]} | {target} | {message} |\n")
        else:
            f.write("✅ 全區無發現事項。\n")
    print(f"報告：{os.path.relpath(md_path, HERE)}")

    if not result["ok"]:
        print("正式區存在需要處理的 fail 項目。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
