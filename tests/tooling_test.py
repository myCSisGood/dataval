#!/usr/bin/env python3
"""本輪新增工具的守門測試：報告分類路徑、report diff、全域圖匯出、advisory prompt。"""
from __future__ import annotations
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dataval import report_paths
from dataval.report import diff_findings
from dataval.graph_export import export_graph
from dataval.advisory_export import build_advisory_prompt
from dataval.parser import parse_ddl


class TestReportPaths(unittest.TestCase):
    def test_primary_domain_prefers_non_common(self):
        self.assertEqual("CRM", report_paths.primary_domain(["Common", "CRM"]))
        self.assertEqual("SCM", report_paths.primary_domain(["SCM", "Common"]))

    def test_primary_domain_fallbacks(self):
        self.assertEqual("Common", report_paths.primary_domain(["Common"]))
        self.assertEqual("_uncategorized", report_paths.primary_domain([]))
        self.assertEqual("_uncategorized", report_paths.primary_domain(None))

    def test_dir_for_creates_and_find_prefers_subfolder(self):
        with tempfile.TemporaryDirectory() as base:
            d = report_paths.report_dir_for(base, ["Common", "PLM"])
            self.assertTrue(d.endswith(os.sep + "PLM"))
            self.assertTrue(os.path.isdir(d))
            with open(os.path.join(d, "foo.report.json"), "w") as f:
                f.write("{}")
            self.assertEqual(os.path.join(d, "foo.report.json"),
                             report_paths.find_report_json(base, "foo"))

    def test_find_flat_fallback_and_missing(self):
        with tempfile.TemporaryDirectory() as base:
            with open(os.path.join(base, "bar.report.json"), "w") as f:
                f.write("{}")
            self.assertEqual(os.path.join(base, "bar.report.json"),
                             report_paths.find_report_json(base, "bar"))
            self.assertIsNone(report_paths.find_report_json(base, "nope"))


class TestDiffFindings(unittest.TestCase):
    def test_added_removed_changed(self):
        old = {"findings": [
            {"check_id": "A", "target": "t", "status": "pass", "message": "ok", "zone": "gating"},
            {"check_id": "B", "target": "t", "status": "fail", "message": "bad", "zone": "gating"}]}
        new = {"findings": [
            {"check_id": "A", "target": "t", "status": "fail", "message": "now bad", "zone": "gating"},
            {"check_id": "C", "target": "t", "status": "warning", "message": "new", "zone": "gating"}]}
        d = diff_findings(old, new)
        self.assertEqual([("C", "t")], [(x["check_id"], x["target"]) for x in d["added"]])
        self.assertEqual([("B", "t")], [(x["check_id"], x["target"]) for x in d["removed"]])
        self.assertEqual(1, len(d["changed"]))
        ch = d["changed"][0]
        self.assertEqual(("A", "t"), (ch["check_id"], ch["target"]))
        self.assertEqual({"from": "pass", "to": "fail"}, ch["fields"]["status"])
        self.assertIn("message", ch["fields"])

    def test_generated_at_is_ignored(self):
        a = {"findings": [], "generated_at": "2026-01-01T00:00:00Z"}
        b = {"findings": [], "generated_at": "2026-07-25T00:00:00Z"}
        self.assertEqual({"added": [], "removed": [], "changed": []}, diff_findings(a, b))


class TestExportGraph(unittest.TestCase):
    def _write_subject(self, prod, domain, name, ddl, relations):
        sub = os.path.join(prod, domain, name)
        os.makedirs(sub)
        with open(os.path.join(sub, f"{name}.sql"), "w") as f:
            f.write(ddl)
        with open(os.path.join(sub, f"{name}.relations.yaml"), "w") as f:
            f.write(relations)
        with open(os.path.join(sub, f"{name}.context.md"), "w") as f:
            f.write("---\nsubject: x\n---\n")

    def test_nodes_and_edges_with_direction(self):
        with tempfile.TemporaryDirectory() as prod:
            self._write_subject(
                prod, "CRM", "sub",
                "CREATE TABLE parent (id UInt64 COMMENT 'x') ENGINE=MergeTree ORDER BY id;\n"
                "CREATE TABLE child (id UInt64 COMMENT 'x', pid UInt64 COMMENT 'x') "
                "ENGINE=MergeTree ORDER BY id;\n",
                "relations:\n  - from: child.pid\n    to: parent.id\n"
                '    cardinality: "N:1"\n')
            g = export_graph(prod)
            ids = {n["id"] for n in g["nodes"]}
            # node id 為 domain 限定的 "<domain>.<table>"（與 _endpoint_key 一致）
            self.assertEqual({"crm.parent", "crm.child"}, ids)
            self.assertEqual("CRM", next(n for n in g["nodes"] if n["id"] == "crm.parent")["domain"])
            # 資料方向：上游(parent, 「1」的一方) → 下游(child)
            self.assertIn({"from": "crm.parent", "to": "crm.child"}, g["edges"])

    def test_domain_filter(self):
        with tempfile.TemporaryDirectory() as prod:
            ddl = "CREATE TABLE t (id UInt64 COMMENT 'x') ENGINE=MergeTree ORDER BY id;\n"
            self._write_subject(prod, "CRM", "a", ddl, "relations: []\n")
            self._write_subject(prod, "SCM", "b", ddl, "relations: []\n")
            only_crm = export_graph(prod, domains=["CRM"])
            self.assertEqual(["CRM"], sorted({n["domain"] for n in only_crm["nodes"]}))


class TestAdvisoryPromptPath(unittest.TestCase):
    def test_prompt_uses_engine_schema_path(self):
        schema = parse_ddl("CREATE TABLE t (id UInt64 COMMENT 'x') "
                           "ENGINE=MergeTree ORDER BY id")
        prompt = build_advisory_prompt(schema, "ctx", name="case")
        # advisory schema 路徑必須指向 _engine/（曾是漏 _engine/ 的 bug）
        self.assertIn("config/_engine/advisory_result.schema.json", prompt)
        self.assertNotIn("`config/advisory_result.schema.json`", prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
