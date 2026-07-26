"""正式區全域關聯圖（subject 之間的 lineage）。

正式區佈局（一 subject 一資料夾）：
    production/<DOMAIN>/<subject>/
        <subject>.sql              已核准 DDL
        <subject>.relations.yaml   關聯宣告（全域圖的邊）
        <subject>.context.md       語意描述（粒度宣告留檔）
        _promotion.yaml            晉升記錄（日期、卡控結果碼、規則版本碼）

relations 進了正式區之後，subject 之間的關聯不再只是單次驗證的輸入，
而是可被合併成一張全域 DAG 的治理資產。本模組提供兩個入口：

  run(schema, relations, production_root)
      驗證「新 subject」對正式區：全域循環（含候選邊）、關聯宣告基數矛盾
      → 會擋；影響分析（候選表在正式區的依賴者）→ 資訊。

  audit(production_root, current_rule_code)
      全區健檢（production_audit.py 用）：三件齊全、DDL 可解析、
      斷鏈、全域循環、基數矛盾、規則版本碼 drift。

完全確定性、無 LLM，屬閘門區。
"""
from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field

import yaml

from .model import Finding, Schema, ZONE_ADVISORY, ZONE_GATING
from .parser import parse_ddl
from .precheck import _parse_endpoint, CARDINALITIES
from .lineage import _has_cycle


def _finding(check_id: str, status: str, target: str, message: str, *,
             zone: str = ZONE_GATING, severity: str | None = None,
             expected: str = "", actual: str = "", fix: str = "") -> Finding:
    if severity is None:
        severity = "error" if status == "fail" else "info"
    return Finding(check_id, "lineage", status, target, message,
                   severity=severity, source="rule", zone=zone,
                   expected=expected, actual=actual, fix=fix)


# ------------------------------------------------------------ 載入正式區

@dataclass
class ProductionSubject:
    domain: str
    name: str
    path: str                      # subject 資料夾（legacy 平鋪檔為其所在資料夾）
    legacy: bool = False           # 舊式平鋪 .sql（無三件套）
    tables: dict = field(default_factory=dict)   # table name -> Table
    relations: list[dict] = field(default_factory=list)  # 已解析 _from/_to
    promotion: dict | None = None
    problems: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)     # 缺的三件套/晉升記錄


def _load_relations(path: str, subject: "ProductionSubject"):
    try:
        with open(path, encoding="utf-8") as f:
            spec = yaml.safe_load(f) or {}
        rels = spec.get("relations")
        if not isinstance(rels, list):
            raise ValueError("根節點必須含 relations: [...]")
    except Exception as e:
        subject.problems.append(
            f"relations.yaml 解析失敗：{type(e).__name__}: {e}")
        return
    for i, rel in enumerate(rels, start=1):
        if not isinstance(rel, dict):
            subject.problems.append(f"relations 第 {i} 條不是 mapping")
            continue
        src = _parse_endpoint(str(rel.get("from", "")))
        dst = _parse_endpoint(str(rel.get("to", "")))
        card = rel.get("cardinality")
        if src is None or dst is None or card not in CARDINALITIES:
            subject.problems.append(f"relations 第 {i} 條格式不合法")
            continue
        rel = dict(rel)
        rel["_from"], rel["_to"] = src, dst
        subject.relations.append(rel)


def load_subjects(production_root: str) -> list[ProductionSubject]:
    """掃 production/<DOMAIN>/：subject 資料夾為主，舊式平鋪 .sql 兼容載入。"""
    out: list[ProductionSubject] = []
    if not production_root or not os.path.isdir(production_root):
        return out
    for domain in sorted(os.listdir(production_root)):
        dpath = os.path.join(production_root, domain)
        if not os.path.isdir(dpath):
            continue
        for entry in sorted(os.listdir(dpath)):
            epath = os.path.join(dpath, entry)
            if os.path.isdir(epath):
                subject = ProductionSubject(domain=domain, name=entry, path=epath)
                ddl_path = os.path.join(epath, entry + ".sql")
                if not os.path.isfile(ddl_path):
                    subject.missing.append(f"{entry}.sql")
                else:
                    try:
                        with open(ddl_path, encoding="utf-8") as f:
                            parsed = parse_ddl(f.read())
                        subject.tables = {t.name: t for t in parsed.tables}
                    except Exception as e:
                        subject.problems.append(
                            f"{entry}.sql 無法解析：{type(e).__name__}: {e}")
                rel_path = os.path.join(epath, entry + ".relations.yaml")
                if not os.path.isfile(rel_path):
                    subject.missing.append(f"{entry}.relations.yaml")
                else:
                    _load_relations(rel_path, subject)
                if not os.path.isfile(os.path.join(epath, entry + ".context.md")):
                    subject.missing.append(f"{entry}.context.md")
                promo_path = os.path.join(epath, "_promotion.yaml")
                if os.path.isfile(promo_path):
                    try:
                        with open(promo_path, encoding="utf-8") as f:
                            subject.promotion = yaml.safe_load(f) or {}
                    except Exception as e:
                        subject.problems.append(
                            f"_promotion.yaml 解析失敗：{type(e).__name__}: {e}")
                else:
                    subject.missing.append("_promotion.yaml")
                out.append(subject)
            elif entry.lower().endswith((".sql", ".ddl")):
                # 舊式平鋪：只有 DDL，無關聯與語意，健檢時提醒遷移
                name = os.path.splitext(entry)[0]
                subject = ProductionSubject(domain=domain, name=name,
                                            path=dpath, legacy=True)
                try:
                    with open(epath, encoding="utf-8") as f:
                        parsed = parse_ddl(f.read())
                    subject.tables = {t.name: t for t in parsed.tables}
                except Exception as e:
                    subject.problems.append(
                        f"{entry} 無法解析：{type(e).__name__}: {e}")
                out.append(subject)
    return out


# ------------------------------------------------------------ 圖與比對

def _pair_key(rel: dict) -> tuple[str, str]:
    """關聯宣告的識別鍵：(from table.col, to table.col)，跨 domain 去前綴。"""
    src, dst = rel["_from"], rel["_to"]
    return (f"{src['table']}.{src['column']}".lower(),
            f"{dst['table']}.{dst['column']}".lower())


def _edges(relations: list[dict]) -> list[tuple[str, str]]:
    """資料方向：to（權威/「1」的一方，上游）→ from（引用方，下游）。"""
    return [(rel["_to"]["table"].lower(), rel["_from"]["table"].lower())
            for rel in relations]


def _declared_cards(subjects: list[ProductionSubject]
                    ) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """pair key -> [(subject 標籤, cardinality)]"""
    out: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for s in subjects:
        for rel in s.relations:
            out.setdefault(_pair_key(rel), []).append(
                (f"{s.domain}/{s.name}", str(rel.get("cardinality"))))
    return out


def export_graph(production_root: str,
                 domains: list[str] | None = None) -> dict:
    """匯出正式區跨 subject 的全域關聯圖，供前端／工具視覺化。

    回傳 {"nodes": [{"id", "domain", "subject"}], "edges": [{"from", "to"}]}。
    重用 load_subjects() 與 _edges()（資料方向：上游→下游），只是把區域變數
    轉成可序列化資料，不重寫掃描邏輯。node id 一律小寫（與 _edges 一致）。
    可用 domains 過濾只匯出指定 domain 的 subject。
    """
    wanted = {d.strip().lower() for d in domains} if domains else None
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edge: set[tuple[str, str]] = set()
    for s in load_subjects(production_root):
        if wanted is not None and s.domain.lower() not in wanted:
            continue
        for tname in s.tables:
            nid = tname.lower()
            nodes.setdefault(nid, {"id": nid, "domain": s.domain,
                                   "subject": s.name})
        for up, down in _edges(s.relations):
            # 端點可能指向他 subject 的表；補成節點（domain 未知標 "?"）。
            for nid in (up, down):
                nodes.setdefault(nid, {"id": nid, "domain": "?", "subject": ""})
            key = (up, down)
            if key not in seen_edge:
                seen_edge.add(key)
                edges.append({"from": up, "to": down})
    return {"nodes": sorted(nodes.values(), key=lambda n: n["id"]),
            "edges": sorted(edges, key=lambda e: (e["from"], e["to"]))}


# ------------------------------------------------------------ 新 subject 驗證

def run(schema: Schema, relations: list[dict] | None,
        production_root: str) -> list[Finding]:
    subjects = load_subjects(production_root)
    relations = relations or []
    if not subjects:
        return [_finding("PRODGRAPH.SCOPE", "skipped", "(production)",
                         "正式區沒有可對照的 data subject，略過全域關聯檢查。")]
    findings: list[Finding] = []

    # ① 全域循環：正式區所有邊 ＋ 候選 subject 的邊
    edges = []
    for s in subjects:
        edges.extend(_edges(s.relations))
    edges.extend(_edges(relations))
    cycle = _has_cycle(edges)
    if cycle:
        findings.append(_finding(
            "PRODGRAPH.CYCLE", "fail", "(全域關聯圖)",
            "本 subject 加入後，正式區的全域關聯圖出現循環依賴。",
            expected="跨 subject 的關聯為無循環有向圖",
            actual="偵測到循環",
            fix="檢視 relations.yaml 的方向宣告；上下游互相引用需拆解。"))

    # ② 關聯宣告基數矛盾：同一對端點在正式區已有不同的 cardinality 宣告
    declared = _declared_cards(subjects)
    conflict = False
    for rel in relations:
        key = _pair_key(rel)
        mine = str(rel.get("cardinality"))
        for owner, theirs in declared.get(key, []):
            if theirs != mine:
                conflict = True
                findings.append(_finding(
                    "PRODGRAPH.CARDINALITY_CONFLICT", "fail",
                    f"{rel['from']} → {rel['to']}",
                    f"本 subject 宣告 {mine}，但正式區 {owner} 對同一對端點"
                    f"宣告 {theirs}。同一關聯的基數不可有兩種說法。",
                    expected=f"與正式區一致（{owner}: {theirs}）",
                    actual=mine,
                    fix="釐清正確基數；修正本 subject 或提請修正正式區宣告。"))

    # ③ 影響分析：候選 DDL 定義的表，在正式區有誰依賴（改動的爆炸半徑）
    local_tables = {t.name.lower() for t in schema.tables}
    dependents: dict[str, list[str]] = {}
    for s in subjects:
        for rel in s.relations:
            up = rel["_to"]["table"].lower()
            if up in local_tables:
                dependents.setdefault(up, []).append(
                    f"{s.domain}/{s.name}（{rel['from']}）")
    for table, deps in sorted(dependents.items()):
        findings.append(_finding(
            "PRODGRAPH.IMPACT", "info", table,
            f"正式區有 {len(deps)} 處依賴此表：{'；'.join(deps)}。"
            "此表的結構或語意變更會影響這些 subject。",
            zone=ZONE_ADVISORY, severity="info",
            fix="變更前通知依賴方；破壞性變更應開新表版本而非原地修改。"))

    # 聚合 pass（與 lineage 的呈現方式一致）
    if not cycle:
        findings.append(_finding("PRODGRAPH.CYCLE", "pass", "(全域關聯圖)",
                                 "加入本 subject 後全域關聯圖無循環。"))
    if not conflict:
        findings.append(_finding(
            "PRODGRAPH.CARDINALITY_CONFLICT", "pass", "(全域關聯圖)",
            "關聯宣告與正式區既有 subject 的基數一致。"))
    return findings


# ------------------------------------------------------------ 全區健檢

def current_rule_code(compiled_path: str) -> str:
    """規則版本碼 = compiled_rules.json 內容的 SHA256（確定性）。"""
    with open(compiled_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]


def audit(production_root: str, rule_code: str | None = None) -> dict:
    """全區健檢。回傳 {subjects, rows, ok}；rows = (等級, 對象, 訊息)。"""
    subjects = load_subjects(production_root)
    rows: list[tuple[str, str, str]] = []

    all_tables: set[str] = set()
    for s in subjects:
        all_tables.update(name.lower() for name in s.tables)

    for s in subjects:
        label = f"{s.domain}/{s.name}"
        if s.legacy:
            rows.append(("warn", label,
                         "舊式平鋪 DDL，缺關聯與語意描述；請以 promote.py 重新晉升遷移。"))
        for m in s.missing:
            level = "warn" if m == "_promotion.yaml" else "fail"
            rows.append((level, label, f"缺 {m}"))
        for p in s.problems:
            rows.append(("fail", label, p))
        # 斷鏈：關聯的 to 端點表在整個正式區都找不到
        for rel in s.relations:
            up = rel["_to"]["table"].lower()
            if up not in all_tables:
                rows.append(("fail", label,
                             f"斷鏈：{rel['from']} → {rel['to']} 的上游表 "
                             f"'{rel['_to']['table']}' 不存在於正式區任何 subject。"))
        # 規則版本碼 drift：舊規則通過的 subject 需要重驗
        if rule_code and s.promotion:
            promoted_code = str(s.promotion.get("rule_version_code", ""))
            if promoted_code and promoted_code != rule_code:
                rows.append(("warn", label,
                             f"規則版本碼 drift：晉升時 {promoted_code}，"
                             f"現行 {rule_code}。規則已演進，建議重驗此 subject。"))

    # 全域循環（僅正式區內部）
    edges = []
    for s in subjects:
        edges.extend(_edges(s.relations))
    if _has_cycle(edges):
        rows.append(("fail", "(全域關聯圖)", "正式區關聯圖存在循環依賴。"))

    # 基數矛盾（正式區內部互相比對）
    for key, owners in _declared_cards(subjects).items():
        cards = {card for _, card in owners}
        if len(cards) > 1:
            detail = "；".join(f"{o}: {c}" for o, c in owners)
            rows.append(("fail", f"{key[0]} → {key[1]}",
                         f"基數宣告矛盾：{detail}"))

    ok = not any(level == "fail" for level, _, _ in rows)
    return {"subjects": subjects, "rows": rows, "ok": ok}
