#!/usr/bin/env python3
"""模擬「目前規則變更」對正式區既有 subject 的影響（純只讀，不改任何檔案）。

    python simulate_impact.py [--production DIR]

原理（不需保存舊 findings 全文，只靠一個不變量）：
  一個正常晉升的 subject，晉升當下閘門區必然零 fail（compliant 才能晉升）。
  所以用**目前磁碟上的 config/** 重跑每個正式區 subject 的閘門檢查後，只要出現
  任何 fail 的 gating finding，就代表它會因規則變更由合規變不合規。

限制（誠實揭露）：
  正式區不存樣本。任何依賴樣本的規則（型別對樣本、join key 編碼一致、
  relations 基數實檢等）在此模擬中無法重新檢驗——這類規則若新增了違規，
  這支工具**看不到**。模擬結果是「至少會壞掉這些」，不是完整清單。

這是獨立指令，不影響 promote.py／rules.py adopt 的既有流程。
"""
from __future__ import annotations
import argparse
import os
import sys

from dataval.engine import load_config, validate
from dataval.llm import NullLLM
from dataval.prodgraph import load_subjects
from dataval.precheck import parse_context, relations_to_lineage
from dataval.report import summarize

import run as R  # 沿用標準 config 路徑（import 不會觸發 run 的 main）

PRODUCTION_ROOT = os.environ.get(
    "DATAVAL_PRODUCTION_DIR", os.path.join(R.HERE, "production"))


def _read_ddl(subject) -> str | None:
    for cand in (os.path.join(subject.path, subject.name + ".sql"),
                 os.path.join(subject.path, subject.name + ".ddl")):
        if os.path.isfile(cand):
            with open(cand, encoding="utf-8") as f:
                return f.read()
    return None


def _read_context(subject) -> tuple[str, list[str], dict[str, list[str]]]:
    """回傳 (context_text, domains, business_keys)，比照晉升時的載入方式。"""
    ctx_path = os.path.join(subject.path, subject.name + ".context.md")
    if not os.path.isfile(ctx_path):
        return "", [], {}
    with open(ctx_path, encoding="utf-8") as f:
        text = f.read()
    meta, _ = parse_context(text)
    domains = meta.get("domains") or []
    domains = [str(d) for d in domains] if isinstance(domains, list) else []
    bkeys = meta.get("business_keys") or {}
    business_keys = ({str(t): [str(c) for c in cols]
                      for t, cols in bkeys.items() if isinstance(cols, list)}
                     if isinstance(bkeys, dict) else {})
    return text.strip(), domains, business_keys


def simulate_subject(subject, cfg, production_root: str) -> tuple[str, list]:
    """回傳 (狀態, blocking_findings)。狀態：compliant / regressed / skipped。"""
    ddl = _read_ddl(subject)
    if ddl is None or not subject.tables:
        return "skipped", []
    context_text, domains, business_keys = _read_context(subject)
    domains = domains or [subject.domain]
    lineage_spec = (relations_to_lineage(subject.relations)
                    if subject.relations else None)
    # sample_data=None 是刻意的：正式區不存樣本（見檔頭「限制」）。
    _schema, findings, _meta = validate(
        ddl, cfg, sample_data=None, context=context_text,
        business_keys=business_keys, lineage_spec=lineage_spec,
        relations=subject.relations, llm=NullLLM(),
        domain_root=R.DOMAIN_ROOT, rules_root=R.RULES_ROOT, domains=domains,
        config_dir=R.CONFIG_DIR, production_root=production_root)
    blocking = [f for f in findings
                if f.zone == "gating" and f.status == "fail"
                and f.severity == "error"]
    return ("regressed" if blocking else "compliant"), blocking


def main():
    ap = argparse.ArgumentParser(
        description="模擬目前規則變更對正式區既有 subject 的影響（只讀）")
    ap.add_argument("--production", default=PRODUCTION_ROOT,
                    help="正式區根目錄（預設 production/）")
    args = ap.parse_args()
    production_root = args.production

    subjects = load_subjects(production_root)
    if not subjects:
        print(f"正式區（{os.path.relpath(production_root, R.HERE)}）沒有 subject，"
              "無可模擬。")
        return

    cfg = load_config(R.CONFIG)
    print("正式區規則影響模擬（規則來源：目前磁碟上的 config/）")
    print(f"掃描 {os.path.relpath(production_root, R.HERE)}/："
          f"找到 {len(subjects)} 個 subject\n")

    regressed = 0
    skipped = 0
    for s in subjects:
        label = f"{s.domain}/{s.name}"
        status, blocking = simulate_subject(s, cfg, production_root)
        if status == "skipped":
            skipped += 1
            print(f"  {label}：⏭️  略過（DDL 無法解析或缺 .sql）")
            continue
        if status == "compliant":
            print(f"  {label}：✅ 維持合規")
            continue
        regressed += 1
        print(f"  {label}：❌ 新增 {len(blocking)} 筆 fail（會由合規變不合規）")
        for f in blocking:
            print(f"     - {f.check_id} @ {f.target}：{f.message}")

    print("\n—— 統計 ——")
    print(f"{len(subjects)} 個 subject 中，{regressed} 個會因目前規則變更而由合規變不合規。"
          + (f"（另有 {skipped} 個因無法解析而略過）" if skipped else ""))
    print("\n⚠️  限制：正式區不存樣本，依賴樣本的規則（型別對樣本、join key 編碼、")
    print("   relations 基數實檢等）在此模擬中無法重新檢驗，這類新違規不會被發現。")
    print("   本結果是「至少會壞掉這些」，不是完整清單。")

    sys.exit(1 if regressed else 0)


if __name__ == "__main__":
    main()
