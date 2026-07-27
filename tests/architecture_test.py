#!/usr/bin/env python3
"""Integration tests for domain scope, key semantics, result contract, and merge guard."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dataval.engine import load_config, validate
from dataval.er_diagram import parse_mermaid
from dataval.model import Finding
from dataval.parser import parse_ddl
from dataval.lineage import run as run_lineage
from dataval.production import run as run_production
from dataval.report import checking_rule_summary, to_html, to_markdown
from dataval.advisory_export import build_advisory_prompt, validate_advisory_result
from merge_advisory import _gating_from_findings, _gating_from_report
from rules import lint_rules
import run as batch_run
from dataval import report_paths


CFG = os.path.join(ROOT, "config", "_engine", "default.yaml")
KW = dict(domain_root=os.path.join(ROOT, "config"),
          rules_root=os.path.join(ROOT, "config", "Common", "knowhow_py"),
          config_dir=os.path.join(ROOT, "config"),
          production_root=os.path.join(ROOT, "production"))


class ArchitectureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg = load_config(CFG)
        with open(os.path.join(ROOT, "input", "subscription", "subscription.sql"),
                  encoding="utf-8") as f:
            cls.ddl = f.read()

    def test_domain_default_is_shared_only(self):
        _, findings, meta = validate(self.ddl, self.cfg, domains=[], **KW)
        self.assertEqual(["Common"], meta["domains_loaded"])
        self.assertEqual([], meta["domains_requested"])
        scope = [f for f in findings if f.check_id == "DOMAIN.SCOPE"]
        self.assertEqual("warning", scope[0].status)
        self.assertFalse(any("plm_" in f.check_id.lower() for f in findings))

    def test_unknown_domain_is_reported_and_skipped(self):
        _, findings, meta = validate(self.ddl, self.cfg,
                                     domains=["CRM", "DOES_NOT_EXIST"], **KW)
        self.assertEqual(["DOES_NOT_EXIST"], meta["domains_unknown"])
        self.assertIn("CRM", meta["domains_loaded"])
        scope = [f for f in findings if f.check_id == "DOMAIN.SCOPE"]
        self.assertEqual("warning", scope[0].status)
        self.assertIn("DOES_NOT_EXIST", scope[0].message)

    def test_every_loaded_rule_has_explicit_result(self):
        _, findings, meta = validate(self.ddl, self.cfg, domains=[], **KW)
        represented = {f.check_id for f in findings}
        missing = set(meta["checking_rule_ids_loaded"]) - represented
        self.assertEqual(set(), missing)
        self.assertTrue(all(f.status in {"pass", "fail", "warning", "info", "skipped"}
                            for f in findings))
        summary = checking_rule_summary(findings, meta["checking_rule_ids_loaded"])
        skipped_ids = {f.check_id for f in findings if f.status == "skipped"}
        self.assertTrue(set(summary["not_checked"]).issubset(skipped_ids))

    def test_rule_coverage_accounts_for_every_config_rule(self):
        """涵蓋帳本：載入 ＋ 未載入 恰好覆蓋 config 全部規則，母體無遺漏。"""
        _, _, meta = validate(self.ddl, self.cfg, domains=["PLM"], **KW)
        cov = meta["rule_coverage"]
        # 母體守恆：total == loaded + not_loaded，兩者不重疊。
        self.assertEqual(cov["rules_total"],
                         cov["rules_loaded_count"] + len(cov["not_loaded"]))
        self.assertEqual(cov["rules_loaded_count"], len(cov["loaded"]))
        loaded_ids = {r["id"] for r in cov["loaded"]}
        not_loaded_ids = {r["id"] for r in cov["not_loaded"]}
        self.assertEqual(set(), loaded_ids & not_loaded_ids)
        # 已載入者恰為引擎實際載入的 checking rule ID。
        self.assertEqual(set(meta["checking_rule_ids_loaded"]), loaded_ids)

    def test_rule_coverage_loads_declared_domain_plus_common(self):
        """宣告 PLM → PLM 與 Common 的規則都在 loaded，其他域落在 not_loaded。"""
        _, _, meta = validate(self.ddl, self.cfg, domains=["PLM"], **KW)
        cov = meta["rule_coverage"]
        loaded_domains = {r["domain"] for r in cov["loaded"]}
        self.assertIn("Common", loaded_domains)
        self.assertIn("PLM", loaded_domains)
        not_loaded_domains = {r["domain"] for r in cov["not_loaded"]}
        # 未宣告的業務域（例如 SCM）不得出現在已載入清單。
        self.assertNotIn("SCM", loaded_domains)
        self.assertIn("SCM", not_loaded_domains)

    def test_rule_coverage_flags_empty_domain(self):
        """空的域（資料夾存在但無規則，如 CRM）要被標出來，不能靜默。"""
        _, _, meta = validate(self.ddl, self.cfg, domains=["CRM"], **KW)
        cov = meta["rule_coverage"]
        self.assertIn("CRM", cov["empty_domains"])
        # 宣告一個空域時，實際生效的仍只有 Common 的規則。
        self.assertTrue(all(r["domain"] == "Common" for r in cov["loaded"]))

    def test_rule_coverage_appears_in_reports(self):
        """三式報告都要呈現涵蓋清單（markdown/html 皆有；json 有結構化鍵）。"""
        from dataval.report import to_json
        _, findings, meta = validate(self.ddl, self.cfg, domains=["PLM"], **KW)
        self.assertIn("規則涵蓋清單", to_markdown(findings, meta))
        self.assertIn("規則涵蓋清單", to_html(findings, meta))
        self.assertIn("rule_coverage", json.loads(to_json(findings, meta)))

    def test_clickhouse_keys_are_separate(self):
        physical_only = parse_ddl(
            "CREATE TABLE t (customer_id UInt64, value String) "
            "ENGINE=MergeTree ORDER BY (customer_id)").tables[0]
        self.assertEqual(["customer_id"], physical_only.sorting_key)
        self.assertEqual([], physical_only.primary_key)
        self.assertEqual([], physical_only.business_key)
        self.assertEqual("", physical_only.business_key_source)

        explicit = parse_ddl(
            "CREATE TABLE t (customer_id UInt64, created_at DateTime, "
            "PRIMARY KEY (customer_id)) ENGINE=MergeTree ORDER BY (created_at)").tables[0]
        self.assertEqual(["created_at"], explicit.sorting_key)
        self.assertEqual(["customer_id"], explicit.primary_key)
        self.assertEqual([], explicit.business_key)

        governed = parse_ddl(
            "CREATE TABLE t (customer_id UInt64, created_at DateTime) "
            "ENGINE=MergeTree ORDER BY (created_at)",
            business_keys={"t": ["customer_id"]}).tables[0]
        self.assertEqual(["customer_id"], governed.business_key)
        self.assertEqual("explicit_metadata", governed.business_key_source)

    def test_advisory_schema_and_prompt(self):
        valid = {"naming_semantic": [], "concept": [], "skills": {}}
        self.assertEqual([], validate_advisory_result(valid))
        self.assertTrue(validate_advisory_result({"concept": [], "skills": {}}))

        schema = parse_ddl(
            "CREATE TABLE t (id UInt64) ENGINE=MergeTree ORDER BY (id)",
            business_keys={"t": ["id"]})
        prompt = build_advisory_prompt(
            schema, "test", name="case",
            pending_skills=[{"id": "semantic_rule", "title": "Semantic",
                             "domain": "Common", "desc": "完整檢查內容"}],
            unregistered_candidates=[{"entity": "x", "table": "t"}])
        self.assertIn("完整檢查內容", prompt)
        self.assertIn("advisory_result.schema.json", prompt)
        self.assertIn('"entity": "x"', prompt)

    def test_rule_lint_contract(self):
        self.assertEqual([], lint_rules())

    def test_production_scope_requires_explicit_domain(self):
        schema = parse_ddl(
            "CREATE TABLE t (client_email String) ENGINE=MergeTree ORDER BY tuple()")
        findings = run_production(
            schema, os.path.join(ROOT, "production"), ["Common"])
        scope = [f for f in findings if f.check_id == "PRODUCTION.SCOPE"]
        self.assertEqual("skipped", scope[0].status)

    def test_production_selected_domain_can_block(self):
        schema = parse_ddl(
            "CREATE TABLE t (client_email String) ENGINE=MergeTree ORDER BY tuple()")
        glossary = {"aliases": {"client": "customer"}}
        findings = run_production(
            schema, os.path.join(ROOT, "production"), ["Common", "CRM"],
            glossary=glossary)
        naming = [f for f in findings
                  if f.check_id == "PRODUCTION.NAMING_CONSISTENCY"]
        self.assertEqual("fail", naming[0].status)
        self.assertIn("customer_email", naming[0].expected)

    def test_production_ignores_unselected_domains(self):
        schema = parse_ddl(
            "CREATE TABLE t (client_email String) ENGINE=MergeTree ORDER BY tuple()")
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "FCM"))
            with open(os.path.join(root, "FCM", "baseline.sql"), "w",
                      encoding="utf-8") as f:
                f.write("CREATE TABLE b (customer_email String) "
                        "ENGINE=MergeTree ORDER BY tuple()")
            findings = run_production(
                schema, root, ["Common", "CRM"],
                glossary={"aliases": {"client": "customer"}})
        self.assertFalse(any(
            f.check_id == "PRODUCTION.NAMING_CONSISTENCY" for f in findings))
        self.assertEqual("skipped", findings[0].status)

    def test_invalid_production_ddl_blocks(self):
        schema = parse_ddl(
            "CREATE TABLE t (id UInt64) ENGINE=MergeTree ORDER BY (id)")
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "CRM"))
            with open(os.path.join(root, "CRM", "broken.sql"), "w",
                      encoding="utf-8") as f:
                f.write("CREATE TABLE (")
            findings = run_production(schema, root, ["Common", "CRM"])
        self.assertEqual("SYSTEM.PRODUCTION_PARSE", findings[0].check_id)
        self.assertEqual("fail", findings[0].status)

    def test_missing_lineage_yaml_suggests_business_key_relationship(self):
        schema = parse_ddl(
            "CREATE TABLE customer (customer_id UInt64) ENGINE=MergeTree "
            "ORDER BY (customer_id); "
            "CREATE TABLE orders (order_id UInt64, customer_id UInt64) "
            "ENGINE=MergeTree ORDER BY (order_id)",
            business_keys={"customer": ["customer_id"]})
        findings, meta = run_lineage(schema, None, ["Common"], "")
        self.assertEqual("suggested", meta["source"])
        self.assertEqual("customer", meta["relationships"][0]["source"])
        self.assertEqual("orders", meta["relationships"][0]["target"])
        self.assertTrue(any(f.check_id == "LINEAGE.SUGGESTION" and
                            f.zone == "advisory" for f in findings))
        metadata = [f for f in findings if f.check_id == "LINEAGE.METADATA"]
        self.assertEqual("skipped", metadata[0].status)

    def test_declared_lineage_validates_and_is_reported(self):
        schema = parse_ddl(
            "CREATE TABLE customer (customer_id UInt64) ENGINE=MergeTree "
            "ORDER BY (customer_id); "
            "CREATE TABLE orders (order_id UInt64, customer_id UInt64) "
            "ENGINE=MergeTree ORDER BY (order_id)")
        spec = {"lineage": {"orders": {
            "upstream": [{"domain": "local", "table": "customer"}],
            "columns": {"customer_id": "local.customer.customer_id"},
        }}}
        findings, lineage_meta = run_lineage(schema, spec, ["Common"], "")
        self.assertFalse(any(f.status == "fail" for f in findings))
        relation = lineage_meta["relationships"][0]
        self.assertEqual("local.customer", relation["source"])
        self.assertEqual([{"source": "customer_id", "target": "customer_id"}],
                         relation["columns"])
        meta = {"lineage": lineage_meta, "checking_rule_ids_loaded": []}
        self.assertIn("local.customer", to_markdown(findings, meta))
        self.assertIn("Lineage 關聯", to_html(findings, meta))

    def test_declared_lineage_type_mismatch_and_cycle_block(self):
        schema = parse_ddl(
            "CREATE TABLE a (id UInt64, b_id UInt64) ENGINE=MergeTree "
            "ORDER BY (id); CREATE TABLE b (id UInt64, a_id String) "
            "ENGINE=MergeTree ORDER BY (id)")
        spec = {"lineage": {
            "a": {
                "upstream": [{"domain": "local", "table": "b"}],
                "columns": {"b_id": "local.b.a_id"},
            },
            "b": {
                "upstream": [{"domain": "local", "table": "a"}],
                "columns": {},
            },
        }}
        findings, _ = run_lineage(schema, spec, ["Common"], "")
        failed = {f.check_id for f in findings if f.status == "fail"}
        self.assertIn("LINEAGE.TYPE_COMPATIBILITY", failed)
        self.assertIn("LINEAGE.CYCLE", failed)

    def test_external_lineage_requires_selected_production_domain(self):
        schema = parse_ddl(
            "CREATE TABLE orders (customer_id UInt64) ENGINE=MergeTree "
            "ORDER BY (customer_id)")
        spec = {"lineage": {"orders": {
            "upstream": [{"domain": "CRM", "table": "customer"}],
            "columns": {"customer_id": "CRM.customer.customer_id"},
        }}}
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "CRM"))
            with open(os.path.join(root, "CRM", "customer.sql"), "w",
                      encoding="utf-8") as f:
                f.write("CREATE TABLE customer (customer_id UInt64) "
                        "ENGINE=MergeTree ORDER BY (customer_id)")
            valid, _ = run_lineage(schema, spec, ["Common", "CRM"], root)
            invalid, _ = run_lineage(schema, spec, ["Common"], root)
        self.assertFalse(any(f.status == "fail" for f in valid))
        self.assertTrue(any(f.check_id == "LINEAGE.DOMAIN_SCOPE" and
                            f.status == "fail" for f in invalid))

    def test_mermaid_er_diagram_becomes_lineage_advisory(self):
        diagram = parse_mermaid("""```mermaid
          erDiagram
          CUSTOMER ||--o{ ORDERS : places
          CUSTOMER {
            UInt64 customer_id PK
          }
          ORDERS {
            UInt64 order_id PK
            UInt64 customer_id FK
          }
        ```
        """, source="case.mmd")
        self.assertEqual([], diagram["errors"])
        self.assertEqual("places", diagram["relationships"][0]["label"])

        schema = parse_ddl(
            "CREATE TABLE customer (customer_id UInt64) ENGINE=MergeTree "
            "ORDER BY (customer_id); CREATE TABLE orders "
            "(order_id UInt64, customer_id UInt64) ENGINE=MergeTree "
            "ORDER BY (order_id)",
            business_keys={"customer": ["customer_id"], "orders": ["order_id"]})
        findings, meta = run_lineage(
            schema, None, ["Common"], "", er_diagram=diagram)
        self.assertEqual("er-diagram", meta["source"])
        self.assertEqual("er-suggested", meta["relationships"][0]["kind"])
        self.assertTrue(any(f.check_id == "LINEAGE.ER_SUGGESTION" and
                            f.zone == "advisory" for f in findings))
        report_meta = {"lineage": meta, "checking_rule_ids_loaded": []}
        self.assertIn("ER diagram 建議", to_markdown(findings, report_meta))
        self.assertIn("ER diagram 建議", to_html(findings, report_meta))

        declared = {"lineage": {"orders": {
            "upstream": [{"domain": "local", "table": "customer"}],
            "columns": {"customer_id": "local.customer.customer_id"},
        }}}
        declared_findings, declared_meta = run_lineage(
            schema, declared, ["Common"], "", er_diagram=diagram)
        self.assertEqual("declared+er-diagram", declared_meta["source"])
        self.assertTrue(declared_meta["relationships"][0]["er_confirmed"])
        self.assertFalse(any(f.status == "fail" for f in declared_findings))

    def test_case_config_parse_errors_become_findings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            ddl_path = os.path.join(temp_dir, "case.sql")
            with open(ddl_path, "w", encoding="utf-8") as f:
                f.write("CREATE TABLE t (id UInt64) ENGINE=MergeTree ORDER BY (id)")
            with open(os.path.join(temp_dir, "case.yaml"), "w",
                      encoding="utf-8") as f:
                f.write("lineage: [")
            diagnostics = []
            spec, source = batch_run.case_config_for(
                ddl_path, diagnostics, case_root=temp_dir)
            self.assertEqual({}, spec)
            self.assertTrue(source.endswith("case.yaml"))
            invalid = {"sample_data": [], "business_keys": [], "lineage": []}
            self.assertIsNone(batch_run.sample_for(invalid, source, diagnostics))
            self.assertEqual({}, batch_run.keys_for(invalid, source, diagnostics))
            self.assertEqual({}, batch_run.lineage_for(invalid, source, diagnostics))
            ids = {finding.check_id for finding in diagnostics}
            self.assertIn("SYSTEM.CASE_CONFIG", ids)
            self.assertIn("SYSTEM.SAMPLE_SPEC", ids)
            self.assertIn("SYSTEM.BUSINESS_KEY_SPEC", ids)
            self.assertIn("SYSTEM.LINEAGE_SPEC", ids)
            self.assertTrue(any(f.status == "fail" for f in diagnostics))

    def test_input_follows_four_piece_contract(self):
        """input/ 的每個 DDL 都要有四件套：samples/、relations.yaml、context.md。"""
        from dataval import precheck as preflight
        input_dir = os.path.join(ROOT, "input")
        subjects = [name for name in os.listdir(input_dir)
                    if os.path.isdir(os.path.join(input_dir, name))]
        self.assertTrue(subjects)
        for subject in subjects:
            base = os.path.join(input_dir, subject)
            ddl = os.path.join(base, subject + ".sql")
            self.assertTrue(os.path.isfile(ddl), subject)
            self.assertTrue(os.path.isdir(os.path.join(base, "samples")), subject)
            self.assertTrue(os.path.isfile(
                os.path.join(base, "relations.yaml")), subject)
            self.assertTrue(os.path.isfile(
                os.path.join(base, "context.md")), subject)
            pre = preflight.run_precheck(ddl)
            self.assertTrue(pre.passed,
                            [i.detail for i in pre.items if not i.ok])

        sub_ddl = os.path.join(input_dir, "subscription", "subscription.sql")
        pre = preflight.run_precheck(sub_ddl)
        case = batch_run.load_input_v2(sub_ddl, pre)
        self.assertEqual("config/Common/cases/subscription.yaml", case.config_source)
        self.assertIn("subscription", case.business_keys)
        self.assertIn("subscription", case.sample)
        self.assertIn("subscription", case.context)

    def test_invalid_business_key_metadata_blocks(self):
        _, findings, _ = validate(
            "CREATE TABLE t (id UInt64) ENGINE=MergeTree ORDER BY (id)",
            self.cfg, domains=[], business_keys={"t": ["missing_id"]}, **KW)
        metadata = [f for f in findings if f.check_id == "BUSINESS_KEY.METADATA"]
        self.assertEqual("fail", metadata[0].status)

    def test_batch_strict_mode_returns_nonzero(self):
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory() as report_dir:
            env["DATAVAL_REPORT_DIR"] = report_dir
            result = subprocess.run(
                [sys.executable, os.path.join(ROOT, "run.py"), "--strict"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False)
            # 報告已依 domain 分類到 reports/<域>/；用 helper 定位 json 後推 html。
            json_path = report_paths.find_report_json(report_dir, "subscription")
            self.assertIsNotNone(json_path, "找不到 subscription.report.json")
            html_path = json_path[: -len(".json")] + ".html"
            self.assertTrue(os.path.isfile(html_path))
            with open(html_path, encoding="utf-8") as f:
                html = f.read()
            self.assertIn("<!DOCTYPE html>", html)
            self.assertIn("語意規則待補完", html)
        self.assertEqual(1, result.returncode, result.stdout + result.stderr)
        self.assertIn("嚴格模式", result.stderr)

    def test_lineage_examples_cover_expected_combinations(self):
        env = dict(os.environ)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["DATAVAL_INPUT_DIR"] = os.path.join(
            ROOT, "examples", "lineage", "input")
        # examples/ 是內部測試 fixtures，走 legacy（config/cases 集中式）輸入
        env["DATAVAL_PRECHECK"] = "legacy"
        with tempfile.TemporaryDirectory() as report_dir:
            env["DATAVAL_REPORT_DIR"] = report_dir
            result = subprocess.run(
                [sys.executable, os.path.join(ROOT, "run.py")],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            def report(name):
                path = report_paths.find_report_json(report_dir, name)
                self.assertIsNotNone(path, f"找不到 {name}.report.json")
                with open(path, encoding="utf-8") as f:
                    return json.load(f)

            valid = report("01_declared_valid")
            mismatch = report("02_declared_type_mismatch")
            cycle = report("03_local_cycle")
            inferred = report("04_inferred_relationship")
            missing = report("05_no_relationship_found")
            standalone = report("06_standalone_declared")
            er_suggestion = report("07_er_diagram_suggestion")

        self.assertTrue(valid["summary"]["compliant"])
        self.assertIn("LINEAGE.TYPE_COMPATIBILITY",
                      mismatch["checking_rule_summary"]["failed"])
        self.assertIn("LINEAGE.CYCLE", cycle["checking_rule_summary"]["failed"])
        self.assertEqual("suggested", inferred["lineage"]["source"])
        self.assertTrue(inferred["lineage"]["relationships"])
        self.assertEqual([], missing["lineage"]["relationships"])
        self.assertIn("沒有足夠可靠", missing["lineage"]["note"])
        self.assertEqual("declared", standalone["lineage"]["source"])
        self.assertIn("已明確宣告無上游", standalone["lineage"]["note"])
        self.assertEqual("er-diagram", er_suggestion["lineage"]["source"])
        self.assertEqual(1, er_suggestion["meta"]["er_diagram"]["relationship_count"])
        self.assertIn("LINEAGE.ER_SUGGESTION",
                      er_suggestion["checking_rule_summary"]["advisory"])

    def test_merge_guard_compares_complete_rule_results(self):
        finding = Finding("RULE.ONE", "structural", "pass", "t", "ok",
                          severity="info", zone="gating")
        with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8",
                                         delete=False) as f:
            json.dump({"gating_zone": {"findings": [finding.to_dict()]}}, f,
                      ensure_ascii=False)
            path = f.name
        try:
            self.assertEqual(_gating_from_report(path), _gating_from_findings([finding]))
            changed = Finding("RULE.ONE", "structural", "fail", "t", "changed",
                              severity="error", zone="gating")
            self.assertNotEqual(_gating_from_report(path), _gating_from_findings([changed]))
        finally:
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
