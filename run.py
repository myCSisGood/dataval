#!/usr/bin/env python3
"""零參數自動執行：掃 input/ 下所有 DDL，逐一驗證並把報告寫到 reports/。

用法（在專案根目錄）：
    python run.py

行為：
  - 自動找 input/ 裡的 *.sql / *.ddl
  - 自動載入 config/cases/<DDL 名>.yaml 的治理設定與少量 sample data
  - 自動載入 config/domains 與 config/rules 裡的規則
  - 每個 DDL 都產生 reports/<名稱>.report.{md,json,html}
  - LLM 看環境變數 DATAVAL_LLM_BASE_URL；沒設就只跑閘門區（仍能出合規判定）
"""
from __future__ import annotations
import json
import os
import sys
from dataclasses import dataclass
import yaml

from dataval.engine import load_config, validate
from dataval.report import to_json, to_markdown, to_html, summarize, blocking_summary
from dataval.llm import from_env
from dataval.advisory_export import build_advisory_prompt
from dataval.subject_summary import build_summary
from dataval.compiler import RuleLoadError, ensure_compiled
from dataval import rules_history
from dataval.er_diagram import parse_mermaid
from dataval.parser import parse_ddl
from dataval.model import Finding, ZONE_ADVISORY, ZONE_GATING
from dataval import precheck as preflight
from dataval import report_paths

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.environ.get("DATAVAL_INPUT_DIR", os.path.join(HERE, "input"))
REPORT_DIR = os.environ.get("DATAVAL_REPORT_DIR", os.path.join(HERE, "reports"))
CONFIG = os.path.join(HERE, "config", "_engine", "default.yaml")
CONFIG_DIR = os.path.join(HERE, "config")
DOMAIN_ROOT = os.path.join(HERE, "config")
RULES_ROOT = os.path.join(HERE, "config", "Common", "knowhow_py")
CASE_CONFIG_ROOT = os.environ.get(
    "DATAVAL_CASE_CONFIG_DIR", "")
ER_DIAGRAM_ROOT = os.environ.get(
    "DATAVAL_ER_DIAGRAM_DIR", "")
PRODUCTION_ROOT = os.path.join(HERE, "production")


@dataclass
class InputCase:
    ddl: str
    sample: dict | None
    context: str
    domains: list[str]
    business_keys: dict[str, list[str]]
    lineage: dict | None
    relations: list | None
    er_diagram: dict | None
    config_source: str
    diagnostics: list[Finding]


def find_ddls() -> list[str]:
    """掃 input/。標準佈局：一 subject 一資料夾 input/<名>/<名>.sql；
    舊式平鋪 input/<名>.sql 相容。"""
    if not os.path.isdir(INPUT_DIR):
        return []
    out = []
    for entry in sorted(os.listdir(INPUT_DIR)):
        path = os.path.join(INPUT_DIR, entry)
        if os.path.isdir(path):
            if entry.endswith(".samples"):
                continue  # 舊式平鋪的樣本資料夾
            for ext in (".sql", ".ddl"):
                ddl = os.path.join(path, entry + ext)
                if os.path.isfile(ddl):
                    out.append(ddl)
                    break
        elif entry.lower().endswith((".sql", ".ddl")):
            out.append(path)
    return out


def _input_diagnostic(check_id: str, target: str, message: str,
                      *, blocking: bool = False) -> Finding:
    return Finding(check_id, "structural", "fail" if blocking else "warning",
                   target, message, severity="error" if blocking else "warning",
                   source="rule", zone=ZONE_GATING,
                   expected="config/cases 設定可正確讀取與解析",
                   actual=message, fix=f"修正檔案 {target}")


def _case_search_roots(case_root: str = "") -> list[str]:
    """個案設定的搜尋順序：環境變數指定 → 各 domain 的 cases/ →
    引擎層 _engine/cases/（內部 fixtures）。"""
    if case_root:
        return [case_root]
    roots = []
    cfg_root = os.path.join(HERE, "config")
    for entry in sorted(os.listdir(cfg_root)):
        dpath = os.path.join(cfg_root, entry, "cases")
        if not entry.startswith("_") and os.path.isdir(dpath):
            roots.append(dpath)
    engine_cases = os.path.join(cfg_root, "_engine", "cases")
    if os.path.isdir(engine_cases):
        roots.append(engine_cases)
    return roots


def case_config_for(ddl_path: str, diagnostics: list[Finding] | None = None,
                    case_root: str = CASE_CONFIG_ROOT) -> tuple[dict, str]:
    """搜尋 config/<域>/cases/<DDL 名>.yaml（個案補充設定）。"""
    name = os.path.splitext(os.path.basename(ddl_path))[0]
    candidates = [os.path.join(root, name + ext)
                  for root in _case_search_roots(case_root)
                  for ext in (".yaml", ".yml")]
    for path in candidates:
        if not os.path.isfile(path):
            continue
        source = os.path.relpath(path, HERE).replace(os.sep, "/")
        try:
            with open(path, encoding="utf-8") as f:
                spec = yaml.safe_load(f) or {}
            if not isinstance(spec, dict):
                raise ValueError("根節點必須是 mapping")
            return spec, source
        except Exception as e:
            if diagnostics is not None:
                diagnostics.append(_input_diagnostic(
                    "SYSTEM.CASE_CONFIG", source,
                    f"case config 解析失敗：{type(e).__name__}: {e}",
                    blocking=True))
            return {}, source
    return {}, ""


def sample_for(spec: dict, source: str,
               diagnostics: list[Finding] | None = None) -> dict | None:
    sample = spec.get("sample_data")
    if sample is None:
        return None
    if isinstance(sample, dict):
        return sample
    if diagnostics is not None:
        diagnostics.append(_input_diagnostic(
            "SYSTEM.SAMPLE_SPEC", source,
            "sample_data 必須是 table -> rows 對照"))
    return None


def context_for(spec: dict, source: str,
                diagnostics: list[Finding] | None = None) -> str:
    context = spec.get("context", "")
    if isinstance(context, str):
        return context.strip()
    if diagnostics is not None:
        diagnostics.append(_input_diagnostic(
            "SYSTEM.CONTEXT_SPEC", source, "context 必須是文字"))
    return ""


def domains_for(spec: dict, source: str,
                diagnostics: list[Finding] | None = None) -> list[str]:
    domains = spec.get("domains")
    if domains is None:
        return []
    if isinstance(domains, list) and all(isinstance(domain, str) for domain in domains):
        return domains
    if diagnostics is not None:
        diagnostics.append(_input_diagnostic(
            "SYSTEM.DOMAIN_SPEC", source, "domains 必須是字串 list"))
    return []


def keys_for(spec: dict, source: str,
             diagnostics: list[Finding] | None = None) -> dict[str, list[str]]:
    keys = spec.get("business_keys")
    if keys is None:
        return {}
    try:
        if not isinstance(keys, dict):
            raise ValueError("business_keys 必須是 table -> columns 對照")
        normalized: dict[str, list[str]] = {}
        for table, columns in keys.items():
            if not isinstance(columns, list) or not columns:
                raise ValueError(f"{table} 的 business key 必須是非空 list")
            normalized[str(table)] = [str(column) for column in columns]
        return normalized
    except Exception as e:
        if diagnostics is not None:
            diagnostics.append(_input_diagnostic(
                "SYSTEM.BUSINESS_KEY_SPEC", source,
                f"business_keys 設定錯誤：{type(e).__name__}: {e}",
                blocking=True))
        return {}


def lineage_for(spec: dict, source: str,
                diagnostics: list[Finding] | None = None) -> dict | None:
    """Load optional explicit design-lineage metadata from the case config."""
    if "lineage" not in spec:
        return None
    lineage = spec.get("lineage")
    if isinstance(lineage, dict):
        return {"lineage": lineage}
    if diagnostics is not None:
        diagnostics.append(_input_diagnostic(
            "SYSTEM.LINEAGE_SPEC", source,
            "lineage 必須是 target table -> relation 的 mapping",
            blocking=True))
    # Empty dict means a declaration exists but is invalid. This avoids
    # turning broken config into a non-blocking suggestion.
    return {}


def er_diagram_for(ddl_path: str, diagnostics: list[Finding] | None = None,
                   er_root: str = ER_DIAGRAM_ROOT) -> dict | None:
    """搜尋個案 ER 圖：config/<域>/cases/<名>.mmd 或 _engine/er_diagrams/。"""
    name = os.path.splitext(os.path.basename(ddl_path))[0]
    for extension in (".mmd", ".mermaid", ".md"):
        roots = ([er_root] if er_root else
                 _case_search_roots() +
                 [os.path.join(HERE, "config", "_engine", "er_diagrams")])
        path = next((p for p in (os.path.join(r, name + extension)
                                 for r in roots)
                     if os.path.isfile(p)),
                    os.path.join(roots[-1], name + extension))
        if not os.path.isfile(path):
            continue
        source = os.path.relpath(path, HERE).replace(os.sep, "/")
        try:
            with open(path, encoding="utf-8") as f:
                diagram = parse_mermaid(f.read(), source=source)
        except Exception as e:
            if diagnostics is not None:
                diagnostics.append(Finding(
                    "SYSTEM.ER_DIAGRAM_PARSE", "lineage", "info", source,
                    f"ER diagram 讀取失敗：{type(e).__name__}: {e}",
                    severity="info", source="rule", zone=ZONE_ADVISORY,
                    fix="修正 Mermaid ER diagram；此問題不影響閘門判定。"))
            return None
        if diagram["errors"] and diagnostics is not None:
            diagnostics.append(Finding(
                "SYSTEM.ER_DIAGRAM_PARSE", "lineage", "info", source,
                "ER diagram 有無法解析的內容：" + "；".join(diagram["errors"]),
                severity="info", source="rule", zone=ZONE_ADVISORY,
                fix="依 config/er_diagrams/README.md 修正 Mermaid 語法。"))
        return diagram
    return None


def load_input(ddl_path: str) -> InputCase:
    """Read one DDL and its same-named config/cases YAML once."""
    diagnostics: list[Finding] = []
    try:
        with open(ddl_path, encoding="utf-8") as f:
            ddl = f.read()
    except Exception as e:
        ddl = ""
        diagnostics.append(_input_diagnostic(
            "SYSTEM.DDL_READ", ddl_path,
            f"DDL 讀取失敗：{type(e).__name__}: {e}", blocking=True))
    spec, config_source = case_config_for(ddl_path, diagnostics)
    return InputCase(
        ddl=ddl,
        sample=sample_for(spec, config_source, diagnostics),
        context=context_for(spec, config_source, diagnostics),
        domains=domains_for(spec, config_source, diagnostics),
        business_keys=keys_for(spec, config_source, diagnostics),
        lineage=lineage_for(spec, config_source, diagnostics),
        relations=None,
        er_diagram=er_diagram_for(ddl_path, diagnostics),
        config_source=config_source,
        diagnostics=diagnostics,
    )


def load_input_v2(ddl_path: str,
                  pre: "preflight.PrecheckResult") -> InputCase:
    """前置檢核通過後，把四件輸入合併成 InputCase。

    config/<域>/cases/<名>.yaml 仍可提供補充設定（如 business_keys、額外 lineage），
    但四件輸入是權威來源：samples 只取 CSV、context 只取 context.md、
    relations.yaml 轉出的 lineage 以表為單位優先於 cases 的 lineage。
    """
    diagnostics: list[Finding] = list(pre.diagnostics)
    spec, config_source = case_config_for(ddl_path, diagnostics)

    business_keys = keys_for(spec, config_source, diagnostics)
    business_keys.update(pre.business_keys)  # front-matter 優先

    legacy_lineage = lineage_for(spec, config_source, diagnostics)
    lineage: dict | None = pre.lineage_spec
    if legacy_lineage and isinstance(legacy_lineage.get("lineage"), dict):
        merged = dict(legacy_lineage["lineage"])
        merged.update((lineage or {}).get("lineage", {}))  # relations 優先
        lineage = {"lineage": merged}

    domains = pre.domains or domains_for(spec, config_source, diagnostics)

    return InputCase(
        ddl=pre.ddl,
        sample=pre.samples or None,
        context=pre.context_text,
        domains=domains,
        business_keys=business_keys,
        lineage=lineage,
        relations=pre.relations,
        er_diagram=merge_domain_erds(
            er_diagram_for(ddl_path, diagnostics), domains,
            {t.name for t in parse_ddl(pre.ddl).tables},
            diagnostics),
        config_source=config_source,
        diagnostics=diagnostics,
    )


def merge_domain_erds(er_diagram: dict | None, domains: list[str] | None,
                      ddl_table_names: set[str],
                      diagnostics: list[Finding]) -> dict | None:
    """疊加 domain 參考 ER 模型（config/domainss/<域>/erd/*.mmd）。

    只取「兩端表都出現在本次 DDL」的關係，供 LINEAGE.ER_SUGGESTION 比對；
    個案 ER 圖（config/<域>/cases/<名>.mmd）優先，domain 模型是補充參照。
    """
    droot = os.path.join(HERE, "config")
    folders = {f.lower(): f for f in os.listdir(droot)
               if os.path.isdir(os.path.join(droot, f))
               and not f.startswith("_")}
    lower_names = {n.lower() for n in ddl_table_names}
    merged = {"source": (er_diagram or {}).get("source", ""),
              "entities": dict((er_diagram or {}).get("entities") or {}),
              "relationships": list((er_diagram or {}).get("relationships") or []),
              "errors": []}
    seen_rel = {(r.get("left"), r.get("right"), r.get("label"))
                for r in merged["relationships"]}
    added = False
    seen_dom: set[str] = set()
    for want in ["Common"] + [d for d in (domains or []) if d]:
        folder = folders.get(want.strip().lower())
        if not folder or folder in seen_dom:
            continue
        seen_dom.add(folder)
        erd_dir = os.path.join(droot, folder, "erd")
        if not os.path.isdir(erd_dir):
            continue
        for fn in sorted(os.listdir(erd_dir)):
            if not fn.endswith((".mmd", ".mermaid")):
                continue
            label = f"{folder}/erd/{fn}"
            try:
                with open(os.path.join(erd_dir, fn), encoding="utf-8") as f:
                    parsed = parse_mermaid(f.read(), source=label)
            except Exception as e:
                diagnostics.append(_input_diagnostic(
                    "SYSTEM.ER_DIAGRAM_PARSE", label,
                    f"domain ER 模型讀取失敗：{type(e).__name__}: {e}"))
                continue
            if parsed.get("errors"):
                diagnostics.append(_input_diagnostic(
                    "SYSTEM.ER_DIAGRAM_PARSE", label,
                    "domain ER 模型有無法解析的行：" + "；".join(parsed["errors"][:3])))
            for rel in parsed.get("relationships") or []:
                left, right = str(rel.get("left")), str(rel.get("right"))
                if left.lower() not in lower_names or right.lower() not in lower_names:
                    continue
                key = (rel.get("left"), rel.get("right"), rel.get("label"))
                if key in seen_rel:
                    continue
                seen_rel.add(key)
                merged["relationships"].append(rel)
                for name in (left, right):
                    merged["entities"].setdefault(
                        name, {"name": name, "columns": []})
                added = True
    if er_diagram is None and not added:
        return None
    if not merged["source"]:
        merged["source"] = "(domain erd 參考模型)"
    return merged


def pending_advisory_specs(findings: list[Finding], compiled_path: str) -> list[dict]:
    pending_ids = {
        f.check_id.replace("SKILL.", "", 1)
        for f in findings
        if f.zone == "advisory" and f.status == "skipped" and
        f.check_id.startswith("SKILL.")
    }
    with open(compiled_path, encoding="utf-8") as f:
        compiled = json.load(f)
    specs = []
    for rule in compiled.get("rules", []):
        if rule.get("id") not in pending_ids or rule.get("kind") != "check-llm":
            continue
        specs.append({
            "id": rule["id"],
            "title": rule.get("title") or rule["id"],
            "domain": rule.get("domain", "Common"),
            "desc": rule.get("check_llm") or "(未提供 check-llm 內容)",
        })
    return specs


def main():
    strict = ("--strict" in sys.argv or
              os.environ.get("DATAVAL_STRICT", "").strip().lower() in
              {"1", "true", "yes", "on"})
    os.makedirs(REPORT_DIR, exist_ok=True)
    report_dir_label = os.path.relpath(REPORT_DIR, HERE)
    ddls = find_ddls()
    if not ddls:
        print(f"找不到 DDL。請把 .sql 或 .ddl 檔放進：{INPUT_DIR}")
        sys.exit(0)

    cfg = load_config(CONFIG)

    # 規則 compile：每次重建結構化內容，有變更才寫入 JSON。
    compiled_target = os.path.join(HERE, "build", "compiled_rules.json")
    previous_rules_text = None
    if os.path.isfile(compiled_target):
        with open(compiled_target, encoding="utf-8") as f:
            previous_rules_text = f.read()
    try:
        compiled_path, recompiled = ensure_compiled(
            DOMAIN_ROOT, RULES_ROOT, compiled_target)
    except RuleLoadError as e:
        print(f"❌ 規則檔載入失敗：\n{e}", file=sys.stderr)
        print("修正上述檔案後重跑；格式見 SKILL_AUTHORING.md。", file=sys.stderr)
        sys.exit(1)
    print(("規則有更新 → 已重新 compile：" if recompiled else "規則未變 → 沿用既有 compile：")
          + os.path.relpath(compiled_path, HERE))
    if recompiled:
        # 規則版控：規則集有變時記錄「加了什麼、拿掉什麼、改了什麼」。
        with open(compiled_path, encoding="utf-8") as f:
            new_rules_text = f.read()
        snapshot = rules_history.record_change(
            previous_rules_text, new_rules_text,
            os.path.join(HERE, "rules_history"))
        if snapshot:
            print("規則版控 → 已記錄變更："
                  + os.path.relpath(snapshot, HERE)
                  + "（摘要見 rules_history/CHANGELOG.md）")
    llm = from_env()
    llm_on = type(llm).__name__ != "NullLLM"

    precheck_mode = os.environ.get("DATAVAL_PRECHECK", "strict").strip().lower()
    print(f"找到 {len(ddls)} 個 DDL；LLM：{'已接' if llm_on else '未接（只跑閘門區）'}"
          + ("" if precheck_mode != "legacy" else "；前置檢核：legacy（相容模式）"))
    any_noncompliant = False
    any_precheck_failed = False
    for ddl_path in ddls:
        name = os.path.splitext(os.path.basename(ddl_path))[0]
        if precheck_mode == "legacy":
            case = load_input(ddl_path)
        else:
            # 前置檢核（存在 → 可解析 → 一致）。四件不齊就不產 report。
            pre = preflight.run_precheck(ddl_path)
            with open(os.path.join(REPORT_DIR, name + ".precheck.md"),
                      "w", encoding="utf-8") as f:
                f.write(preflight.to_markdown(pre))
            for line in preflight.console_lines(pre):
                print("  " + line)
            if not pre.passed:
                any_precheck_failed = True
                print(f"     → 補齊後重跑；缺件明細見 "
                      f"{report_dir_label}/{name}.precheck.md")
                continue
            case = load_input_v2(ddl_path, pre)
        schema, findings, meta = validate(
            case.ddl, cfg, sample_data=case.sample, context=case.context,
            business_keys=case.business_keys, lineage_spec=case.lineage,
            relations=case.relations, er_diagram=case.er_diagram,
            diagnostics=case.diagnostics, llm=llm,
            domain_root=DOMAIN_ROOT, rules_root=RULES_ROOT, domains=case.domains,
            config_dir=CONFIG_DIR, production_root=PRODUCTION_ROOT)
        meta["case_config"] = case.config_source

        # 依代表性 domain 把報告分類到 reports/<域>/。此時 domains 已知
        # （驗證已回傳 meta），所以三式報告、advisory_prompt、subject_summary
        # 都放進分類資料夾；precheck.md 例外——它可能在完全不知道 domain 時就
        # 失敗，故維持扁平放在 reports/ 根（見上方 precheck 寫檔）。
        out_dir = report_paths.report_dir_for(REPORT_DIR, meta.get("domains_loaded"))
        md_path = os.path.join(out_dir, name + ".report.md")
        js_path = os.path.join(out_dir, name + ".report.json")
        html_path = os.path.join(out_dir, name + ".report.html")
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(to_markdown(findings, meta))
        with open(js_path, "w", encoding="utf-8") as f:
            f.write(to_json(findings, meta))
        # HTML 永遠產生。未接 LLM 時顧問區會標示待補完，但所有確定性
        # checking rule ID、lineage 與合規判定仍可直接閱讀。
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(to_html(findings, meta))

        # If Python has no LLM, export an advisory prompt for the opencode agent
        # to complete with ITS llm; agent writes <name>.advisory_result.json then
        # runs `python merge_advisory.py` to fill the advisory zone in the HTML.
        if not llm_on:
            pending = pending_advisory_specs(findings, compiled_path)
            prompt = build_advisory_prompt(schema, case.context,
                                           name=name, pending_skills=pending,
                                           unregistered_candidates=meta.get(
                                               "unregistered_candidates", []))
            with open(os.path.join(out_dir, name + ".advisory_prompt.md"),
                      "w", encoding="utf-8") as f:
                f.write(prompt)

        s = summarize(findings)
        flag = "✅ 合規" if s["compliant"] else f"❌ 不合規（會擋 {s['blocking_count']}）"
        bs = blocking_summary(findings)
        if bs["blocked"]:
            rules = "、".join(b["rule"] for b in bs["blocked"])
            flag += f" ｜ 卡下來的規則：{rules}"
        any_noncompliant = any_noncompliant or not s["compliant"]
        dom_str = "、".join(meta.get("domains_loaded", [])) or "(無)"

        # 跑完 data governance 流程後，自動產生這個 data subject 的摘要與用途。
        # 放到 reports/<名>.subject_summary.md，作為放入 production 前的說明文件。
        summary_md = build_summary(schema, meta.get("domains_loaded"),
                                   s["compliant"], llm)
        with open(os.path.join(out_dir, name + ".subject_summary.md"),
                  "w", encoding="utf-8") as f:
            f.write(summary_md)

        html_label = os.path.relpath(html_path, HERE)
        print(f"  {name}: {flag} ｜ domain: {dom_str} → "
              f"{html_label}"
              f"（＋摘要 {name}.subject_summary.md）")

    print(f"完成。報告在 {report_dir_label}/ 資料夾。")
    if not llm_on:
        print("（HTML 已產生；未接本地 LLM 的語意規則會標示待補完。若要補齊，"
              "可依 *.advisory_prompt.md 產出 advisory_result.json，再執行 "
              "python merge_advisory.py。）")
    if any_precheck_failed:
        print("有 data subject 輸入不齊全，未產生報告。四件輸入格式見 "
              "input/README.md；缺件明細見 reports/*.precheck.md。",
              file=sys.stderr)
        sys.exit(2)
    if strict and any_noncompliant:
        print("嚴格模式：存在不合規 DDL。", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
