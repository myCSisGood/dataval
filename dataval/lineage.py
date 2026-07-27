"""Small, explicit design-lineage validator.

Declared lineage is deterministic and may block. When no relations metadata is
present, only conservative local candidates are returned as advisory findings.
The module describes design intent; it does not claim to observe runtime jobs.
"""
from __future__ import annotations

import os

from .model import Finding, Schema, Table, ZONE_ADVISORY, ZONE_GATING
from .parser import parse_ddl
from .skills import COMMON_DOMAIN


def _finding(check_id: str, status: str, target: str, message: str,
             *, expected: str = "", actual: str = "", fix: str = "") -> Finding:
    return Finding(
        check_id, "lineage", status, target, message,
        severity="error" if status == "fail" else "info",
        source="rule", zone=ZONE_GATING,
        expected=expected, actual=actual, fix=fix)


def _relationship(source: str, target: str, kind: str,
                  columns: list[dict] | None = None, label: str = "") -> dict:
    relationship = {
        "source": source,
        "target": target,
        "kind": kind,
        "columns": columns or [],
    }
    if label:
        relationship["label"] = label
    return relationship


def _er_suggestions(schema: Schema, er_diagram: dict | None
                    ) -> tuple[list[dict], list[str]]:
    """Convert ER associations into conservative lineage candidates."""
    if not er_diagram:
        return [], []
    tables = {table.name.lower(): table for table in schema.tables}
    entities = {name.lower(): value for name, value in
                (er_diagram.get("entities") or {}).items()}
    out: list[dict] = []
    unmatched: list[str] = []

    def flagged(entity_name: str, flag: str) -> set[str]:
        entity = entities.get(entity_name.lower()) or {}
        return {
            column.get("name", "") for column in entity.get("columns", [])
            if flag in column.get("flags", [])
        }

    for relation in er_diagram.get("relationships") or []:
        left_name = str(relation.get("left", ""))
        right_name = str(relation.get("right", ""))
        left = tables.get(left_name.lower())
        right = tables.get(right_name.lower())
        if left is None or right is None:
            unmatched.append(f"{left_name} ↔ {right_name}")
            continue

        left_pk = set(left.business_key) or flagged(left_name, "PK")
        right_pk = set(right.business_key) or flagged(right_name, "PK")
        left_fk = flagged(left_name, "FK")
        right_fk = flagged(right_name, "FK")
        left_columns = {column.name for column in left.columns}
        right_columns = {column.name for column in right.columns}

        if left_pk and left_pk <= right_columns and (
                not right_fk or left_pk <= right_fk):
            source, target, keys, kind = left, right, left_pk, "er-suggested"
        elif right_pk and right_pk <= left_columns and (
                not left_fk or right_pk <= left_fk):
            source, target, keys, kind = right, left, right_pk, "er-suggested"
        else:
            source, target, kind = left, right, "er-undirected"
            keys = {
                name for name in left_columns & right_columns
                if name.lower().endswith("_id")
            }
        out.append(_relationship(
            source.name, target.name, kind,
            [{"source": key, "target": key} for key in sorted(keys)],
            label=str(relation.get("label", ""))))
    return out, unmatched


def _er_finding(relation: dict) -> Finding:
    direction = "→" if relation["kind"] == "er-suggested" else "↔"
    columns = "、".join(
        f"{item['source']} → {item['target']}"
        for item in relation["columns"]) or "未找到可確認的識別欄位"
    return Finding(
        "LINEAGE.ER_SUGGESTION", "lineage", "info",
        f"{relation['source']} {direction} {relation['target']}",
        f"Mermaid ER diagram 顯示結構關聯（{columns}）；請確認資料流向後寫入 relations.yaml。",
        severity="info", source="rule", zone=ZONE_ADVISORY,
        rationale="ER diagram 描述實體關係，不等於已觀測到 ETL/runtime lineage。",
        fix="在 relations.yaml 明確宣告 from、to 與 cardinality。")


def _suggest(schema: Schema, er_diagram: dict | None = None
             ) -> tuple[list[Finding], dict]:
    """Suggest conservative local relationships without asserting lineage."""
    er_relationships, unmatched_er = _er_suggestions(schema, er_diagram)
    relationships: list[dict] = list(er_relationships)
    seen: set[tuple[str, str]] = set()

    # An explicitly declared business key is the strongest local signal: if
    # another table carries every key column, the first table may feed it.
    if not relationships:
        for source in sorted(schema.tables, key=lambda table: table.name):
            if not source.business_key:
                continue
            for target in sorted(schema.tables, key=lambda table: table.name):
                if source.name == target.name:
                    continue
                if all(target.col(column) for column in source.business_key):
                    pair = (source.name, target.name)
                    seen.add(pair)
                    relationships.append(_relationship(
                        source.name, target.name, "suggested",
                        [{"source": column, "target": column}
                         for column in source.business_key]))

    # If business-key metadata yields no candidate, shared *_id columns are a
    # weaker hint. Use a neutral relation so direction is not invented.
    if not relationships:
        tables = sorted(schema.tables, key=lambda table: table.name)
        for index, left in enumerate(tables):
            left_ids = {column.name for column in left.columns
                        if column.name.lower().endswith("_id")}
            for right in tables[index + 1:]:
                shared = sorted(left_ids & {
                    column.name for column in right.columns
                    if column.name.lower().endswith("_id")
                })
                if not shared:
                    continue
                pair = (left.name, right.name)
                if pair in seen:
                    continue
                relationships.append(_relationship(
                    left.name, right.name, "suggested-undirected",
                    [{"source": column, "target": column} for column in shared]))

    findings = [_finding(
        "LINEAGE.METADATA", "skipped", "(lineage)",
        "未提供明確 relations／lineage 宣告；lineage 不納入閘門卡控。")]
    findings.extend(_er_finding(relation) for relation in er_relationships)
    if unmatched_er:
        findings.append(Finding(
            "LINEAGE.ER_SUGGESTION", "lineage", "info", "(ER diagram)",
            f"ER diagram 關係無法對應本次 DDL 表名：{unmatched_er}。",
            severity="info", source="rule", zone=ZONE_ADVISORY,
            fix="讓 Mermaid entity 名稱與 DDL table 名稱一致。"))
    if relationships:
        for relation in relationships:
            if relation["kind"].startswith("er-"):
                continue
            columns = "、".join(
                f"{item['source']} → {item['target']}"
                for item in relation["columns"])
            direction = "→" if relation["kind"] == "suggested" else "↔"
            findings.append(Finding(
                "LINEAGE.SUGGESTION", "lineage", "info",
                f"{relation['source']} {direction} {relation['target']}",
                f"可能存在關聯（共同識別欄位：{columns}）；請確認方向後寫入 relations.yaml。",
                severity="info", source="rule", zone=ZONE_ADVISORY,
                rationale="此關係由 Business Key 或共用 *_id 推測，並非已證實的執行血緣。",
                fix="在 relations.yaml 明確宣告 from、to 與 cardinality。"))
        if er_relationships:
            note = "未設定 relations；以下關係來自 ER diagram，需由 owner 確認方向。"
        else:
            note = "未設定 relations；以下關係是系統建議，需由 owner 確認。"
    else:
        findings.append(Finding(
            "LINEAGE.SUGGESTION", "lineage", "info", "(lineage)",
            "找不到足以建議的關聯；若此設計確實沒有上游，請用 upstream: [] 明確宣告。",
            severity="info", source="rule", zone=ZONE_ADVISORY,
            rationale="沒有明確 Business Key 關聯或共用 *_id，系統不猜測資料流向。",
            fix="在 relations.yaml 建立關聯；獨立資料主體可設定 relations: []。"))
        note = "未設定 relations，也沒有足夠可靠的候選關係。"
    return findings, {
        "source": "er-diagram" if er_relationships else "suggested",
        "relationships": relationships,
        "note": note,
    }


def _production_catalog(production_root: str, domains: list[str],
                        dialect: str) -> dict[tuple[str, str], Table]:
    """Load selected production tables; parse errors are reported upstream."""
    catalog: dict[tuple[str, str], Table] = {}
    if not production_root or not os.path.isdir(production_root):
        return catalog
    available = {
        name.lower(): name for name in os.listdir(production_root)
        if os.path.isdir(os.path.join(production_root, name))
    }
    for requested in sorted(domains):
        domain = available.get(requested.lower())
        if domain is None:
            continue
        directory = os.path.join(production_root, domain)
        sql_paths = sorted(
            os.path.join(root, filename)
            for root, _, files in os.walk(directory)
            for filename in files
            if filename.lower().endswith((".sql", ".ddl")))
        for path in sql_paths:
            try:
                with open(path, encoding="utf-8") as file:
                    parsed = parse_ddl(file.read(), dialect=dialect)
            except Exception:
                continue
            for table in parsed.tables:
                catalog[(domain.lower(), table.name)] = table
    return catalog


def _has_cycle(edges: list[tuple[str, str]]) -> bool:
    graph: dict[str, list[str]] = {}
    for source, target in edges:
        graph.setdefault(source, []).append(target)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(next_node) for next_node in graph.get(node, [])):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in sorted(graph))


def run(schema: Schema, lineage_spec: dict | None,
        domains_loaded: list[str] | None, production_root: str,
        dialect: str = "clickhouse", *, er_diagram: dict | None = None
        ) -> tuple[list[Finding], dict]:
    """Validate declared lineage or return non-blocking relationship hints."""
    if lineage_spec is None:
        return _suggest(schema, er_diagram)

    empty_meta = {"source": "declared", "relationships": [], "note": ""}
    if not isinstance(lineage_spec, dict) or not isinstance(
            lineage_spec.get("lineage"), dict):
        return [_finding(
            "LINEAGE.METADATA", "fail", "(lineage)",
            "relations.yaml 轉換後的 lineage 必須是 target table 對照。",
            expected="lineage 為 target table 對照", actual=str(lineage_spec),
            fix="依 input/README.md 修正 relations.yaml。")], empty_meta

    declared = lineage_spec["lineage"]
    selected = [domain for domain in (domains_loaded or [])
                if domain.lower() != COMMON_DOMAIN.lower()]
    selected_by_lower = {domain.lower(): domain for domain in selected}
    catalog = _production_catalog(production_root, selected, dialect)
    findings: list[Finding] = []
    relationships: list[dict] = []
    local_edges: list[tuple[str, str]] = []
    metadata_valid = True
    upstream_valid = True
    domain_valid = True
    columns_valid = True
    types_valid = True

    for target_name, config in sorted(declared.items(), key=lambda item: str(item[0])):
        target_name = str(target_name)
        target = schema.table(target_name)
        if target is None or not isinstance(config, dict):
            metadata_valid = False
            findings.append(_finding(
                "LINEAGE.METADATA", "fail", target_name,
                "lineage 目標表不存在，或設定不是 mapping。",
                expected="目標表存在於本次 DDL，設定為 mapping",
                actual="目標表不存在或格式錯誤",
                fix="修正 lineage 的目標表名與縮排。"))
            continue
        upstream = config.get("upstream")
        columns = config.get("columns", {})
        if not isinstance(upstream, list) or not isinstance(columns, dict):
            metadata_valid = False
            findings.append(_finding(
                "LINEAGE.METADATA", "fail", target_name,
                "upstream 必須是 list，columns 必須是 mapping。",
                expected="upstream: [...] 與 columns: {...}",
                actual=f"upstream={type(upstream).__name__}, columns={type(columns).__name__}",
                fix="依 lineage 範本修正資料結構。"))
            continue

        sources: dict[str, tuple[str, Table | None]] = {}
        for item in upstream:
            if not isinstance(item, dict) or not item.get("domain") or not item.get("table"):
                metadata_valid = False
                findings.append(_finding(
                    "LINEAGE.METADATA", "fail", target_name,
                    "每個 upstream 必須包含 domain 與 table。",
                    expected="- domain: CRM\n  table: dim_customer",
                    actual=str(item), fix="補齊 upstream 的 domain 與 table。"))
                continue
            requested_domain = str(item["domain"])
            source_table_name = str(item["table"])
            source_ref = f"{requested_domain}.{source_table_name}"
            if requested_domain.lower() == "local":
                source_table = schema.table(source_table_name)
                local_edges.append((source_table_name, target_name))
            else:
                actual_domain = selected_by_lower.get(requested_domain.lower())
                if actual_domain is None:
                    domain_valid = False
                    source_table = None
                    findings.append(_finding(
                        "LINEAGE.DOMAIN_SCOPE", "fail", source_ref,
                        f"上游 domain '{requested_domain}' 未由 context.md 的 domains 選取。",
                        expected="lineage domain 已明確選入 context.md 的 domains",
                        actual=f"本次選取 {selected}",
                        fix=f"將 {requested_domain} 加入 context.md 的 domains。"))
                else:
                    source_table = catalog.get((actual_domain.lower(), source_table_name))
            sources[source_ref.lower()] = (source_ref, source_table)
            if source_table is None:
                upstream_valid = False
                findings.append(_finding(
                    "LINEAGE.UPSTREAM_EXISTS", "fail", source_ref,
                    "找不到宣告的上游資料表。",
                    expected="local DDL 或已選 domain 的 production 中存在此表",
                    actual="找不到", fix="修正表名、domain，或先核准 production DDL。"))
            relationships.append(_relationship(source_ref, target_name, "declared"))

        for target_column_name, source_path in sorted(columns.items()):
            target_column_name = str(target_column_name)
            parts = str(source_path).split(".")
            if len(parts) != 3:
                columns_valid = False
                findings.append(_finding(
                    "LINEAGE.COLUMN_EXISTS", "fail",
                    f"{target_name}.{target_column_name}",
                    f"來源欄位 '{source_path}' 必須使用 domain.table.column 格式。",
                    expected="DOMAIN.table.column", actual=str(source_path),
                    fix="修正 columns 的來源欄位路徑。"))
                continue
            source_domain, source_table_name, source_column_name = parts
            source_ref = f"{source_domain}.{source_table_name}"
            source_entry = sources.get(source_ref.lower())
            source_table = source_entry[1] if source_entry else None
            target_column = target.col(target_column_name)
            source_column = source_table.col(source_column_name) if source_table else None
            if source_entry is None or target_column is None or source_column is None:
                columns_valid = False
                missing = []
                if source_entry is None:
                    missing.append("來源未列在 upstream")
                if target_column is None:
                    missing.append("目標欄位不存在")
                if source_entry is not None and source_column is None:
                    missing.append("來源欄位不存在")
                findings.append(_finding(
                    "LINEAGE.COLUMN_EXISTS", "fail",
                    f"{source_path} → {target_name}.{target_column_name}",
                    f"欄位映射無法解析：{'、'.join(missing)}。",
                    expected="來源已宣告且來源／目標欄位都存在",
                    actual="、".join(missing), fix="修正 upstream 或 columns 映射。"))
                continue
            if target_column.base_type != source_column.base_type:
                types_valid = False
                findings.append(_finding(
                    "LINEAGE.TYPE_COMPATIBILITY", "fail",
                    f"{source_path} → {target_name}.{target_column_name}",
                    "lineage 來源與目標欄位型別不相容。",
                    expected=f"目標基本型別 {source_column.base_type}",
                    actual=f"目標基本型別 {target_column.base_type}",
                    fix="調整目標型別或改正 lineage 欄位映射。"))
            for relation in relationships:
                if relation["source"].lower() == source_ref.lower() and relation["target"] == target_name:
                    relation["columns"].append({
                        "source": source_column_name,
                        "target": target_column_name,
                    })
                    break

    cycle = _has_cycle(local_edges)
    if cycle:
        findings.append(_finding(
            "LINEAGE.CYCLE", "fail", "(lineage)",
            "本次 DDL 宣告的 local lineage 形成循環。",
            expected="來源到目標為無循環有向圖", actual="偵測到循環",
            fix="修正 upstream 方向，或移除互相依賴。"))

    aggregate = (
        ("LINEAGE.METADATA", metadata_valid, "relations.yaml 的 lineage 格式與目標表有效。"),
        ("LINEAGE.DOMAIN_SCOPE", domain_valid, "所有外部上游 domain 都已明確選取。"),
        ("LINEAGE.UPSTREAM_EXISTS", upstream_valid, "所有宣告的上游資料表都存在。"),
        ("LINEAGE.COLUMN_EXISTS", columns_valid, "所有 lineage 欄位映射都可解析。"),
        ("LINEAGE.TYPE_COMPATIBILITY", types_valid, "所有 lineage 欄位基本型別相容。"),
        ("LINEAGE.CYCLE", not cycle, "local lineage 未形成循環。"),
    )
    existing_fail_ids = {finding.check_id for finding in findings
                         if finding.status == "fail"}
    for check_id, valid, message in aggregate:
        if valid and check_id not in existing_fail_ids:
            findings.append(_finding(check_id, "pass", "(lineage)", message))

    er_relationships, unmatched_er = _er_suggestions(schema, er_diagram)
    declared_pairs = {
        frozenset((relation["source"].split(".")[-1].lower(),
                   relation["target"].lower()))
        for relation in relationships
    }
    for er_relation in er_relationships:
        pair = frozenset((er_relation["source"].lower(),
                          er_relation["target"].lower()))
        if pair in declared_pairs:
            for declared_relation in relationships:
                declared_pair = frozenset((
                    declared_relation["source"].split(".")[-1].lower(),
                    declared_relation["target"].lower()))
                if declared_pair == pair:
                    declared_relation["er_confirmed"] = True
                    break
            continue
        relationships.append(er_relation)
        findings.append(_er_finding(er_relation))
    if unmatched_er:
        findings.append(Finding(
            "LINEAGE.ER_SUGGESTION", "lineage", "info", "(ER diagram)",
            f"ER diagram 關係無法對應本次 DDL 表名：{unmatched_er}。",
            severity="info", source="rule", zone=ZONE_ADVISORY,
            fix="讓 Mermaid entity 名稱與 DDL table 名稱一致。"))

    if not relationships and metadata_valid:
        note = "已明確宣告無上游關聯（upstream: []）。"
    elif er_relationships:
        note = ("關係來自 relations.yaml，並參照 ER diagram；兩者都是設計宣告，"
                "不代表已觀測到 runtime lineage。")
    else:
        note = "關係來自 relations.yaml；這是設計宣告，不代表已觀測到執行血緣。"
    return findings, {
        "source": "declared+er-diagram" if er_relationships else "declared",
        "relationships": relationships,
        "note": note,
    }
