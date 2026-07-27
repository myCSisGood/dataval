"""Engine: orchestrates the full pipeline from the architecture diagram.

Flow: parse -> compiled skills -> metadata checks -> production/lineage -> report.
The concept layer runs in the advisory zone.

Core architectural rule enforced here:
  Any finding from an LLM source is FORCED to the advisory zone and info severity,
  so it can never affect the compliance verdict. Rule/skill findings stay gating.
"""
from __future__ import annotations
import os
import yaml
from .parser import parse_ddl
from .model import Finding, ZONE_GATING, ZONE_ADVISORY
from .llm import LLMClient, NullLLM
from .skills import COMMON_DOMAIN, SkillRegistry
from . import concept, lineage, production, subject_inference


def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_glossary(config_dir: str, domains: list[str] | None = None,
                  problems: list[str] | None = None) -> dict:
    """合併詞彙字典。基底：config/Common/naming/glossary.yaml；
    再依請求的 domain 疊加各自的 naming/glossary.yaml（後載入者可增補／覆蓋）。
    相容：舊式 config/glossary.yaml 若存在會先併入。"""
    merged: dict = {"banned_terms": {}, "aliases": {}, "standard_terms": []}
    paths: list[str] = []
    legacy = os.path.join(config_dir, "glossary.yaml")
    if os.path.isfile(legacy):
        paths.append(legacy)
    domains_root = config_dir
    if os.path.isdir(os.path.join(config_dir, "domains")):
        domains_root = os.path.join(config_dir, "domains")  # 舊佈局相容
    if os.path.isdir(domains_root):
        folders = {f.lower(): f for f in os.listdir(domains_root)
                   if os.path.isdir(os.path.join(domains_root, f))
                   and not f.startswith("_")}
        seen: set[str] = set()
        for want in ["Common"] + [d for d in (domains or []) if d]:
            folder = folders.get(want.strip().lower())
            if not folder or folder in seen:
                continue
            seen.add(folder)
            path = os.path.join(domains_root, folder, "naming", "glossary.yaml")
            if os.path.isfile(path):
                paths.append(path)
    for path in paths:
        label = os.path.relpath(path).replace(os.sep, "/")
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise ValueError("根節點必須是 mapping")
            for key in ("banned_terms", "aliases"):
                value = data.get(key) or {}
                if not isinstance(value, dict):
                    raise ValueError(f"{key} 必須是「詞: 標準詞」對照表")
                merged[key].update(value)
            terms = data.get("standard_terms") or []
            if not isinstance(terms, list):
                raise ValueError("standard_terms 必須是清單")
            for term in terms:
                if term not in merged["standard_terms"]:
                    merged["standard_terms"].append(term)
        except Exception as e:
            if problems is not None:
                problems.append(f"{label}：{type(e).__name__}: {e}")
    return merged


def _rule_coverage(reg) -> dict:
    """規則涵蓋帳本：以 config 完整規則清單為母體，交代每一條的去向。

    不改變任何合規判定，也不改動載入邏輯（仍是 Common ＋ context.md 宣告的域）。
    純粹讓報告能回答：「我宣告的域，底下每條規則是否都執行了？被略過的是哪些、為什麼？」

    分三類：
      loaded        — 本次載入並執行的規則（結果另由 checking rule ID 摘要呈現）
      not_loaded    — 規則存在於 config，但所屬域未被 context.md 宣告而未載入
      empty_domains — config 有此域資料夾卻無任何規則（例如 CRM 這類 stub 域）
    """
    loaded_ids = set(reg.loaded_rule_ids)
    inventory = list(reg.inventory)
    loaded = sorted(
        (r for r in inventory if r["id"] in loaded_ids),
        key=lambda r: (r["domain"], r["id"]))
    not_loaded = sorted(
        (r for r in inventory if r["id"] not in loaded_ids),
        key=lambda r: (r["domain"], r["id"]))
    domains_with_rules = {r["domain"] for r in inventory}
    empty_domains = sorted(
        d for d in reg.available_domains if d not in domains_with_rules)
    return {
        "available_domains": list(reg.available_domains),
        "loaded_domains": list(reg.loaded_domains),
        "requested_domains": list(reg.requested_domains),
        "unknown_domains": list(reg.unknown_domains),
        "rules_total": len(inventory),
        "rules_loaded_count": len(loaded),
        "loaded": loaded,
        "not_loaded": not_loaded,
        "empty_domains": empty_domains,
    }


def _enforce_zone(f: Finding) -> Finding:
    """Enforce the hard gating/advisory boundary.

    Rule (structural, not just convention): anything that is LLM-derived OR
    already marked advisory is forced into the advisory zone and demoted to info,
    so it can NEVER contribute to the compliance verdict. Only deterministic
    rule/skill findings remain in the gating zone. This is what guarantees the
    gating result is reproducible: no LLM output can leak into it.
    """
    is_llm = (f.source == "llm")
    is_advisory = (f.zone == ZONE_ADVISORY)
    if is_llm or is_advisory:
        f.zone = ZONE_ADVISORY
        # advisory never blocks: collapse any fail/warning to info
        if f.status in ("fail", "warning"):
            f.status = "info"
        f.severity = "info"
        if f.source != "skill":   # keep skill provenance; otherwise mark llm
            f.source = "llm" if is_llm else f.source
    else:
        f.zone = ZONE_GATING
    return f


def load_ssot(config_dir: str, domains: list[str] | None,
              base: dict | None = None,
              problems: list[str] | None = None) -> dict:
    """合併 SSOT registry。Common/ssot/registry.yaml 為基底,
    請求的 domain 疊加各自的 ssot/registry.yaml。
    registry / attribute_owner 為 dict 疊加覆蓋;清單類為保序聯集。"""
    merged = {k: (dict(v) if isinstance(v, dict) else
                  (list(v) if isinstance(v, list) else v))
              for k, v in (base or {}).items()}
    droot = config_dir
    if os.path.isdir(os.path.join(config_dir, "domains")):
        droot = os.path.join(config_dir, "domains")
    if not os.path.isdir(droot):
        return merged
    folders = {f.lower(): f for f in os.listdir(droot)
               if os.path.isdir(os.path.join(droot, f))
               and not f.startswith("_")}
    seen: set[str] = set()
    for want in ["Common"] + [d for d in (domains or []) if d]:
        folder = folders.get(want.strip().lower())
        if not folder or folder in seen:
            continue
        seen.add(folder)
        path = os.path.join(droot, folder, "ssot", "registry.yaml")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise ValueError("根節點必須是 mapping")
        except Exception as e:
            if problems is not None:
                problems.append(
                    os.path.relpath(path).replace(os.sep, "/")
                    + f"：{type(e).__name__}: {e}")
            continue
        for key, value in data.items():
            if isinstance(value, dict):
                target = merged.setdefault(key, {})
                if isinstance(target, dict):
                    target.update(value)
            elif isinstance(value, list):
                target = merged.setdefault(key, [])
                if isinstance(target, list):
                    for item in value:
                        if item not in target:
                            target.append(item)
            else:
                merged[key] = value
    return merged


def validate(ddl: str, cfg: dict, dialect: str = "clickhouse",
             sample_data: dict | None = None, context: str = "",
             business_keys: dict[str, list[str]] | None = None,
             lineage_spec: dict | None = None,
             relations: list | None = None,
             er_diagram: dict | None = None,
             diagnostics: list[Finding] | None = None,
             llm: LLMClient | None = None,
             domain_root: str = "", rules_root: str = "",
             domains: list[str] | None = None,
             config_dir: str = "config", production_root: str = "production"):
    llm = llm or NullLLM()
    business_keys = business_keys or {}
    schema = parse_ddl(ddl, dialect=dialect, sample_data=sample_data, context=context,
                       business_keys=business_keys)
    config_problems: list[str] = []
    glossary = load_glossary(config_dir, domains, problems=config_problems)
    # SSOT registry 按域合併(config/<域>/ssot/registry.yaml);cfg 其餘鍵不動。
    cfg = dict(cfg or {})
    cfg["ssot"] = load_ssot(config_dir, domains, base=cfg.get("ssot") or {},
                            problems=config_problems)

    # 規則 build 整合進主流程：先產生結構化的 compiled JSON，
    # 內容有變更才寫入，再「從 compiled JSON 載入」規則來執行。
    # .md 是撰寫格式；build/compiled_rules.json 是執行格式（單一執行來源）。
    from .compiler import ensure_compiled
    build_dir = os.path.join(os.path.dirname(os.path.abspath(config_dir)), "build")
    os.makedirs(build_dir, exist_ok=True)
    compiled_path, _ = ensure_compiled(
        domain_root, rules_root,
        os.path.join(build_dir, "compiled_rules.json"))

    findings: list[Finding] = list(diagnostics or [])
    for problem in config_problems:
        findings.append(Finding(
            "SYSTEM.CONFIG_SPEC", "structural", "warning",
            problem.split("：")[0],
            f"設定檔無法使用（已略過該檔，其餘設定照常合併）：{problem}",
            severity="warning", source="rule", zone=ZONE_GATING,
            fix="修正該 YAML 後重跑；壞檔不會靜默消失，但也不會中斷驗證。"))
    # 規則只有一個家：全部經由 compiled JSON 載入執行。
    # 確定性規則進閘門；```check-llm 進顧問。閘門路徑零 LLM。
    reg = SkillRegistry()
    reg.load_compiled(compiled_path, domains=domains, config_dir=config_dir)
    findings += reg.run(schema, llm, glossary, cfg)
    domains_loaded = reg.loaded_domains
    rule_coverage = _rule_coverage(reg)

    # Business key metadata is explicit and independently validated. A sorting
    # key or ClickHouse PRIMARY KEY never silently becomes a business key.
    key_errors: list[Finding] = []
    for table_name, keys in sorted(business_keys.items()):
        table = schema.table(table_name)
        if table is None:
            key_errors.append(Finding(
                "BUSINESS_KEY.METADATA", "structural", "fail", table_name,
                f"Business key metadata 指向不存在的表 '{table_name}'。",
                severity="error", source="rule", zone=ZONE_GATING,
                expected="metadata 表名存在於 DDL", actual="DDL 無此表",
                fix="修正 context.md front-matter 的 business_keys 表名"))
            continue
        missing = [key for key in keys if table.col(str(key)) is None]
        if missing:
            key_errors.append(Finding(
                "BUSINESS_KEY.METADATA", "structural", "fail", table_name,
                f"Business key metadata 含不存在欄位 {missing}。",
                severity="error", source="rule", zone=ZONE_GATING,
                expected="business key 欄位存在於表", actual=f"缺少 {missing}",
                fix="修正 context.md 的 business_keys 或補上 DDL 欄位"))
    if key_errors:
        findings += key_errors
    elif business_keys:
        findings.append(Finding(
            "BUSINESS_KEY.METADATA", "structural", "pass", "(schema)",
            f"Business key metadata 已驗證：{sorted(business_keys)}。",
            severity="info", source="rule", zone=ZONE_GATING))
    else:
        findings.append(Finding(
            "BUSINESS_KEY.METADATA", "structural", "skipped", "(schema)",
            "context.md 未提供 business_keys，無法確認 business key。",
            severity="info", source="rule", zone=ZONE_GATING))

    # Domain scope is an explicit checking result. Missing selection is safe:
    # only Common runs, and the report warns instead of silently loading all.
    if reg.unknown_domains:
        findings.append(Finding(
            "DOMAIN.SCOPE", "structural", "warning", "(domains)",
            f"未知 domain：{reg.unknown_domains}；已略過，本次載入 {domains_loaded}。",
            severity="warning", source="rule", zone=ZONE_GATING,
            expected="domain 存在於 config/<domain>",
            actual=f"未知 {reg.unknown_domains}",
            fix="修正 context.md 的 domains 或建立對應 domain 目錄"))
    elif not reg.requested_domains:
        findings.append(Finding(
            "DOMAIN.SCOPE", "structural", "warning", "(domains)",
            f"未指定 domain，依安全預設只載入 {COMMON_DOMAIN}。",
            severity="warning", source="rule", zone=ZONE_GATING,
            expected="在 context.md front-matter 明確指定業務 domain",
            actual="未指定", fix="新增 domains；若確定只需共用規則可保持現狀"))
    else:
        findings.append(Finding(
            "DOMAIN.SCOPE", "structural", "pass", "(domains)",
            f"Domain 範圍已明確：{domains_loaded}。",
            severity="info", source="rule", zone=ZONE_GATING))

    # advisory concept layer (subject correctness)
    findings += concept.run(schema, llm)

    # Production baseline: selected domains reference approved DDL naming.
    findings += production.run(
        schema, production_root, domains_loaded, dialect, glossary)

    # 正式區全域關聯圖：subject 之間的循環／基數矛盾（會擋）與影響分析（資訊）。
    from . import prodgraph
    candidate_domains = [domain for domain in domains_loaded
                         if domain.lower() != COMMON_DOMAIN.lower()]
    candidate_domain = candidate_domains[0] if len(candidate_domains) == 1 else ""
    findings += prodgraph.run(
        schema, relations, production_root, candidate_domain=candidate_domain)

    # E2E 流程情境：標註本次的表位於哪些 domain 流程的哪一站（資訊，不擋）。
    from . import flows as domain_flows
    findings += domain_flows.run(schema, domains_loaded, config_dir)

    # Design lineage is explicit governance metadata. Declared relationships
    # are deterministic gating checks; absent metadata yields advisory hints.
    lineage_findings, lineage_meta = lineage.run(
        schema, lineage_spec, domains_loaded, production_root, dialect,
        er_diagram=er_diagram)
    findings += lineage_findings

    # SSOT 未登錄主體推斷 — 確定性啟發層（警告放行）。候選清單供顧問區產草稿。
    inf_findings, unreg_candidates = subject_inference.run(schema, cfg, glossary)
    findings += inf_findings

    findings = [_enforce_zone(f) for f in findings]

    # Deterministic ordering so the same input always yields byte-identical
    # report bodies (excluding the timestamp). Sort by a stable key.
    findings.sort(key=lambda f: (f.category, f.zone, f.check_id, f.target,
                                 f.status, f.message))

    meta = {"dialect": dialect, "tables": len(schema.tables),
            "skills_loaded": reg.count(),
            "domains_loaded": reg.loaded_domains,
            "domains_requested": reg.requested_domains,
            "domains_unknown": reg.unknown_domains,
            "checking_rule_ids_loaded": reg.loaded_rule_ids,
            "rule_coverage": rule_coverage,
            "lineage": lineage_meta,
            "er_diagram": {
                "source": (er_diagram or {}).get("source", ""),
                "entities": sorted((er_diagram or {}).get("entities", {})),
                "relationship_count": len(
                    (er_diagram or {}).get("relationships", [])),
            },
            "unregistered_candidates": unreg_candidates}
    return schema, findings, meta
