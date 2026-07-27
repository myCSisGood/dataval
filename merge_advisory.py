#!/usr/bin/env python3
"""把 agent 補完的顧問區建議合併進報告（含 HTML）。

用法（agent 產生 reports/<名>.advisory_result.json 後執行）：
    python merge_advisory.py

它會：
  1. 重跑每個 input/ DDL 的 gating 檢查（確保每條 checking rule ID 的閘門結果不變）。
  2. 讀 reports/<名>.advisory_result.json，把 agent 產生的建議轉成顧問區 findings。
  3. 重繪 reports/<名>.report.{md,json,html}，顧問區顯示真實建議。

閘門區完全不受影響（agent 的建議一律進顧問區、標 info、永不擋）。
"""
from __future__ import annotations
import argparse
import json
import os
import sys

from dataval.engine import load_config, validate
from dataval.report import to_json, to_markdown, to_html, summarize
from dataval.model import Finding, ZONE_ADVISORY
from dataval.llm import NullLLM
from dataval.advisory_export import validate_advisory_result

import run as R  # reuse paths + the single DDL/case-config loader


def _load_case(ddl_path: str):
    """Use the same strict/legacy input contract as run.py."""
    mode = os.environ.get("DATAVAL_PRECHECK", "strict").strip().lower()
    if mode == "legacy":
        return R.load_input(ddl_path)
    pre = R.preflight.run_precheck(ddl_path)
    if not pre.passed:
        details = "；".join(item.detail for item in pre.items if not item.ok)
        raise ValueError(f"四件輸入未通過前置檢核：{details}")
    return R.load_input_v2(ddl_path, pre)


def _advisory_complete(report_path: str) -> tuple[bool, str]:
    if not os.path.isfile(report_path):
        return False, "缺 report.json"
    try:
        with open(report_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except Exception as error:
        return False, f"report.json 無法讀取：{error}"
    if (payload.get("meta") or {}).get("advisory_merged"):
        return True, "已由 agent 合併"
    findings = (payload.get("advisory_zone") or {}).get("findings")
    if not isinstance(findings, list):
        return False, "報告缺 advisory_zone.findings"
    pending = [finding for finding in findings
               if finding.get("status") == "skipped" and
               finding.get("source") == "llm"]
    if pending:
        return False, f"仍有 {len(pending)} 項語意檢查待補"
    return True, "顧問區沒有待補項目"


def status(ddls: list[str]) -> int:
    incomplete = 0
    for ddl_path in ddls:
        name = os.path.splitext(os.path.basename(ddl_path))[0]
        complete, detail = _advisory_complete(
            os.path.join(R.REPORT_DIR, name + ".report.json"))
        print(f"  {'✅' if complete else '❌'} {name}: {detail}")
        incomplete += 0 if complete else 1
    if not ddls:
        print("找不到任何 DDL。")
        return 1
    if incomplete:
        print(f"❌ {incomplete} 份報告的顧問區尚未完成。")
        return 1
    print("✅ 所有報告的顧問區均已完成。")
    return 0


def _canonical_gating(items: list[dict]) -> list[str]:
    """Direct, hash-free comparison form for complete gating findings."""
    return sorted(json.dumps(item, ensure_ascii=False, sort_keys=True)
                  for item in items)


def _gating_from_report(path: str) -> list[str]:
    with open(path, encoding="utf-8") as f:
        payload = json.load(f)
    items = (payload.get("gating_zone") or {}).get("findings")
    if not isinstance(items, list):
        raise ValueError("報告缺少 gating_zone.findings")
    return _canonical_gating(items)


def _gating_from_findings(findings: list[Finding]) -> list[str]:
    return _canonical_gating([f.to_dict() for f in findings if f.zone == "gating"])


def _advisory_from_result(result: dict) -> list[Finding]:
    out: list[Finding] = []
    def mk(check_id, items):
        for it in (items or []):
            out.append(Finding(check_id, "naming" if "naming" in check_id else "concept",
                               "info", str(it.get("target", "(schema)")),
                               str(it.get("message", "")), severity="info",
                               rationale=str(it.get("rationale", "")),
                               source="llm", zone=ZONE_ADVISORY))
    mk("NAME.SEMANTIC", result.get("naming_semantic"))
    mk("CONCEPT.SUBJECT", result.get("concept"))
    for sid, items in (result.get("skills") or {}).items():
        for it in items:
            out.append(Finding(f"SKILL.{sid}", "best_practice", "info",
                               str(it.get("target", "(schema)")),
                               str(it.get("message", "")), severity="info",
                               rationale=str(it.get("rationale", "")),
                               source="llm", zone=ZONE_ADVISORY))
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--status", action="store_true",
                        help="只檢查所有報告的顧問區是否已補完")
    args = parser.parse_args()
    cfg = load_config(R.CONFIG)
    ddls = R.find_ddls()
    if args.status:
        sys.exit(status(ddls))
    merged = 0
    guard_failed = 0
    for ddl_path in ddls:
        name = os.path.splitext(os.path.basename(ddl_path))[0]
        result_path = os.path.join(R.REPORT_DIR, name + ".advisory_result.json")
        if not os.path.isfile(result_path):
            continue
        try:
            with open(result_path, encoding="utf-8") as f:
                result = json.load(f)
        except Exception as e:
            print(f"  {name}: 讀取 advisory_result 失敗（{e}），略過")
            guard_failed += 1
            continue
        schema_errors = validate_advisory_result(result)
        if schema_errors:
            print(f"  {name}: advisory_result 不符合 "
                  "config/_engine/advisory_result.schema.json")
            for error in schema_errors:
                print(f"    - {error}")
            guard_failed += 1
            continue

        try:
            case = _load_case(ddl_path)
        except Exception as error:
            print(f"  {name}: 無法依目前輸入契約載入（{error}），停止合併")
            guard_failed += 1
            continue
        report_path = os.path.join(R.REPORT_DIR, name + ".report.json")
        try:
            previous_gating = _gating_from_report(report_path)
        except Exception as e:
            print(f"  {name}: 無法讀取合併前閘門結果（{e}），停止合併")
            guard_failed += 1
            continue

        # 重跑（NullLLM）取得穩定的 gating findings，再把 agent 建議加進顧問區
        schema, findings, meta = validate(
            case.ddl, cfg, sample_data=case.sample, context=case.context,
            business_keys=case.business_keys, lineage_spec=case.lineage,
            relations=case.relations,
            er_diagram=case.er_diagram,
            diagnostics=case.diagnostics, llm=NullLLM(),
            domain_root=R.DOMAIN_ROOT, rules_root=R.RULES_ROOT,
            domains=case.domains,
            config_dir=R.CONFIG_DIR, production_root=R.PRODUCTION_ROOT)
        meta["case_config"] = case.config_source
        compiled_path = os.path.join(R.HERE, "build", "compiled_rules.json")
        meta["validation_manifest"] = R.validation_manifest(ddl_path, compiled_path)
        meta["rule_version_code"] = meta["validation_manifest"][
            "validation_bundle_code"]

        current_gating = _gating_from_findings(findings)
        if current_gating != previous_gating:
            before_ids = sorted(json.loads(x)["check_id"] for x in previous_gating)
            after_ids = sorted(json.loads(x)["check_id"] for x in current_gating)
            print(f"  {name}: 閘門保護失敗，合併前後 checking rule 結果不同，已停止寫入")
            print(f"    合併前 rule IDs：{before_ids}")
            print(f"    重跑後 rule IDs：{after_ids}")
            guard_failed += 1
            continue

        # 移除「待補完」佔位（未接 LLM 的 info 佔位），換成 agent 的真實建議
        placeholder_ids = {"NAME.SEMANTIC", "CONCEPT.SKIPPED", "BP.LLM", "SSOT.LLM"}
        findings = [f for f in findings
                    if not (f.zone == ZONE_ADVISORY and
                            (f.check_id in placeholder_ids or "略過語意卡控" in f.message
                             or (f.source == "llm" and f.status == "skipped")))]
        findings += _advisory_from_result(result)
        findings.sort(key=lambda f: (f.category, f.zone, f.check_id, f.target,
                                     f.status, f.message))
        meta["advisory_merged"] = True

        outputs = {
            ".report.md": to_markdown(findings, meta),
            ".report.json": to_json(findings, meta),
            ".report.html": to_html(findings, meta),
        }
        for suffix, content in outputs.items():
            with open(os.path.join(R.REPORT_DIR, name + suffix), "w",
                      encoding="utf-8") as f:
                f.write(content)
        s = summarize(findings)
        print(f"  {name}: 顧問區已補完（{s['advisory']} 項）→ reports/{name}.report.html")
        merged += 1

    if merged == 0 and guard_failed == 0:
        print("找不到任何 advisory_result.json。請先讓 agent 依 advisory_prompt.md 產生建議。")
    elif merged:
        print(f"完成，合併 {merged} 份。閘門區判定不變。")
    if guard_failed:
        print(f"❌ {guard_failed} 份報告未通過 JSON Schema 或閘門保護，未合併。")
        sys.exit(1)


if __name__ == "__main__":
    main()
