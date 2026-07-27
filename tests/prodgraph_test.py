"""正式區全域關聯圖與晉升流程的守門測試。

守的保證：
  G1 全域循環（含候選邊）→ 會擋
  G2 同一對端點的基數矛盾 → 會擋
  G3 候選表在正式區有依賴者 → 影響分析（資訊，不擋）
  G4 全區健檢：斷鏈 fail、legacy 平鋪 warn、規則版本碼 drift warn
  G5 晉升閘門：不合規的 subject 不能晉升；晉升記錄帶雙碼
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import yaml  # noqa: E402

from dataval import prodgraph  # noqa: E402
from dataval.parser import parse_ddl  # noqa: E402
from dataval.precheck import _parse_endpoint  # noqa: E402
from dataval.provenance import sha256_file, validation_manifest  # noqa: E402


def write(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def make_subject(prod: str, domain: str, name: str, ddl: str,
                 relations_yaml: str = "relations: []\n",
                 promotion: dict | None = None):
    base = os.path.join(prod, domain, name)
    write(os.path.join(base, f"{name}.sql"), ddl)
    write(os.path.join(base, f"{name}.relations.yaml"), relations_yaml)
    write(os.path.join(base, f"{name}.context.md"),
          f"---\nsubject: {name}\n---\n## 粒度\n一行=一筆。\n")
    if promotion is not None:
        with open(os.path.join(base, "_promotion.yaml"), "w",
                  encoding="utf-8") as f:
            yaml.safe_dump(promotion, f, allow_unicode=True)
    return base


def rel(from_: str, to: str, card: str = "N:1") -> dict:
    return {"from": from_, "to": to, "cardinality": card,
            "_from": _parse_endpoint(from_), "_to": _parse_endpoint(to)}


DDL_A = ("CREATE TABLE a (a_id UInt64 COMMENT 'x', b_id UInt64 COMMENT 'y') "
         "ENGINE=MergeTree() ORDER BY (a_id);")
DDL_B = ("CREATE TABLE b (b_id UInt64 COMMENT 'x', a_id UInt64 COMMENT 'y') "
         "ENGINE=MergeTree() ORDER BY (b_id);")


class ProdgraphCase(unittest.TestCase):
    def setUp(self):
        self.prod = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.prod)


class T_G1_GlobalCycleBlocks(ProdgraphCase):
    def test_candidate_edge_closes_cycle(self):
        # 正式區：a 依賴 b（b 是上游）。候選宣告 b 依賴 a → 循環。
        make_subject(self.prod, "X", "subj_a", DDL_A,
                     "relations:\n  - from: a.b_id\n    to: b.b_id\n"
                     "    cardinality: \"N:1\"\n")
        schema = parse_ddl(DDL_B)
        findings = prodgraph.run(
            schema, [rel("b.a_id", "a.a_id")], self.prod,
            candidate_domain="X")
        cycle = [f for f in findings if f.check_id == "PRODGRAPH.CYCLE"]
        self.assertEqual("fail", cycle[0].status)
        self.assertEqual("gating", cycle[0].zone)


class T_G2_CardinalityConflictBlocks(ProdgraphCase):
    def test_same_pair_different_cardinality(self):
        make_subject(self.prod, "X", "subj_a", DDL_A,
                     "relations:\n  - from: a.b_id\n    to: b.b_id\n"
                     "    cardinality: \"N:1\"\n")
        schema = parse_ddl(DDL_A)
        findings = prodgraph.run(
            schema, [rel("a.b_id", "b.b_id", "N:M")], self.prod,
            candidate_domain="X")
        conflict = [f for f in findings
                    if f.check_id == "PRODGRAPH.CARDINALITY_CONFLICT"]
        self.assertEqual("fail", conflict[0].status)

    def test_same_cardinality_passes(self):
        make_subject(self.prod, "X", "subj_a", DDL_A,
                     "relations:\n  - from: a.b_id\n    to: b.b_id\n"
                     "    cardinality: \"N:1\"\n")
        schema = parse_ddl(DDL_A)
        findings = prodgraph.run(
            schema, [rel("a.b_id", "b.b_id", "N:1")], self.prod,
            candidate_domain="X")
        conflict = [f for f in findings
                    if f.check_id == "PRODGRAPH.CARDINALITY_CONFLICT"]
        self.assertEqual("pass", conflict[0].status)


class T_G3_ImpactAnalysisInfo(ProdgraphCase):
    def test_dependents_listed_as_info(self):
        # 正式區 subj_a 依賴表 b；候選 DDL 定義了 b → 影響分析。
        make_subject(self.prod, "X", "subj_a", DDL_A,
                     "relations:\n  - from: a.b_id\n    to: b.b_id\n"
                     "    cardinality: \"N:1\"\n")
        schema = parse_ddl(DDL_B)
        findings = prodgraph.run(schema, [], self.prod, candidate_domain="X")
        impact = [f for f in findings if f.check_id == "PRODGRAPH.IMPACT"]
        self.assertEqual(1, len(impact))
        self.assertEqual("info", impact[0].status)
        self.assertEqual("advisory", impact[0].zone)
        self.assertIn("X/subj_a", impact[0].message)


class T_G4_Audit(ProdgraphCase):
    def test_broken_link_fails_and_drift_warns(self):
        make_subject(
            self.prod, "X", "subj_a", DDL_A,
            "relations:\n  - from: a.b_id\n    to: ghost.b_id\n"
            "    cardinality: \"N:1\"\n",
            promotion={"rule_version_code": "old_code"})
        result = prodgraph.audit(self.prod, rule_code="new_code")
        levels = {(lvl, msg.split("：")[0]) for lvl, _, msg in result["rows"]}
        self.assertFalse(result["ok"])
        self.assertIn(("fail", "斷鏈"), levels)
        self.assertIn(("warn", "規則版本碼 drift"), levels)

    def test_legacy_flat_ddl_warns(self):
        write(os.path.join(self.prod, "X", "old_table.sql"), DDL_A)
        result = prodgraph.audit(self.prod)
        self.assertTrue(any(lvl == "warn" and "舊式平鋪" in msg
                            for lvl, _, msg in result["rows"]))
        self.assertTrue(result["ok"])  # legacy 只提醒不 fail

    def test_domain_qualified_nodes_do_not_form_false_cycle(self):
        make_subject(
            self.prod, "X", "subj_x", DDL_A,
            "relations:\n  - from: a.b_id\n    to: b.b_id\n"
            "    cardinality: \"N:1\"\n")
        make_subject(
            self.prod, "Y", "subj_y", DDL_B,
            "relations:\n  - from: b.a_id\n    to: a.a_id\n"
            "    cardinality: \"N:1\"\n")
        result = prodgraph.audit(self.prod)
        self.assertFalse(any("循環" in message for _, _, message in result["rows"]))

    def test_external_domain_cannot_be_satisfied_by_same_table_in_other_domain(self):
        make_subject(self.prod, "CRM", "customer", DDL_A)
        make_subject(
            self.prod, "SCM", "consumer", DDL_B,
            "relations:\n  - from: b.a_id\n    to: FCM.a.a_id\n"
            "    cardinality: \"N:1\"\n")
        result = prodgraph.audit(self.prod)
        self.assertTrue(any(
            level == "fail" and "FCM.a.a_id" in message
            for level, _, message in result["rows"]))

    def test_promoted_asset_hash_drift_fails(self):
        base = make_subject(self.prod, "X", "subj_a", DDL_A)
        paths = {
            "ddl": os.path.join(base, "subj_a.sql"),
            "relations": os.path.join(base, "subj_a.relations.yaml"),
            "context": os.path.join(base, "subj_a.context.md"),
        }
        with open(os.path.join(base, "_promotion.yaml"), "w", encoding="utf-8") as f:
            yaml.safe_dump({"input_hashes": {k: sha256_file(v)
                                              for k, v in paths.items()}}, f)
        write(paths["context"], "tampered\n")
        result = prodgraph.audit(self.prod)
        self.assertTrue(any(
            level == "fail" and "完整性" in message
            for level, _, message in result["rows"]))


class T_G5_PromotionGate(unittest.TestCase):
    def _compliant_fixture(self, tmp: str, name: str = "good"):
        inp = os.path.join(tmp, "input")
        rep = os.path.join(tmp, "reports")
        prod = os.path.join(tmp, "production")
        ddl = os.path.join(inp, f"{name}.sql")
        write(ddl, DDL_A)
        write(os.path.join(inp, f"{name}.relations.yaml"), "relations: []\n")
        write(os.path.join(inp, f"{name}.context.md"),
              f"---\nsubject: {name}\ndomains: [X]\n---\n## 粒度\n一行=一筆。\n")
        write(os.path.join(inp, f"{name}.samples", "a.csv"), "a_id,b_id\n1,2\n")
        manifest = validation_manifest(
            ddl, os.path.join(ROOT, "build", "compiled_rules.json"))
        write(os.path.join(rep, f"{name}.report.json"), json.dumps({
            "summary": {"compliant": True},
            "meta": {"validation_manifest": manifest},
            "findings": [],
        }))
        env = dict(os.environ, DATAVAL_INPUT_DIR=inp,
                   DATAVAL_REPORT_DIR=rep, DATAVAL_PRODUCTION_DIR=prod,
                   PYTHONDONTWRITEBYTECODE="1")
        return inp, rep, prod, ddl, env

    def test_noncompliant_subject_cannot_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = os.path.join(tmp, "input")
            rep = os.path.join(tmp, "reports")
            prod = os.path.join(tmp, "production")
            write(os.path.join(inp, "bad.sql"), DDL_A)
            write(os.path.join(inp, "bad.relations.yaml"), "relations: []\n")
            write(os.path.join(inp, "bad.context.md"),
                  "---\nsubject: bad\ndomains: [X]\n---\n## 粒度\n一行=一筆。\n")
            write(os.path.join(inp, "bad.samples", "a.csv"), "a_id,b_id\n1,2\n")
            write(os.path.join(rep, "bad.report.json"), json.dumps(
                {"summary": {"compliant": False},
                 "blocking_summary": {"blocked": [{"rule": "SKILL.x"}]},
                 "findings": []}))
            env = dict(os.environ, DATAVAL_INPUT_DIR=inp,
                       DATAVAL_REPORT_DIR=rep, DATAVAL_PRODUCTION_DIR=prod,
                       PYTHONDONTWRITEBYTECODE="1")
            result = subprocess.run(
                [sys.executable, os.path.join(ROOT, "promote.py"), "bad"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False)
            self.assertEqual(1, result.returncode)
            self.assertIn("不合規", result.stderr)
            self.assertFalse(os.path.isdir(os.path.join(prod, "X", "bad")))

    def test_gate_result_code_is_order_insensitive(self):
        import promote
        f1 = {"check_id": "A", "status": "pass", "target": "t", "zone": "gating"}
        f2 = {"check_id": "B", "status": "fail", "target": "u", "zone": "gating"}
        adv = {"check_id": "C", "status": "info", "target": "v",
               "zone": "advisory"}
        a = promote.gate_result_code({"findings": [f1, f2, adv]})
        b = promote.gate_result_code({"findings": [f2, f1]})  # 順序無關、顧問區不計
        self.assertEqual(a, b)

    def test_stale_compliant_report_cannot_promote(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp, rep, prod, ddl, env = self._compliant_fixture(tmp)
            context = os.path.join(inp, "good.context.md")
            write(context,
                  "---\nsubject: good\ndomains: [X]\n---\n## 粒度\n已修改。\n")
            result = subprocess.run(
                [sys.executable, os.path.join(ROOT, "promote.py"), "good"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False)
            self.assertEqual(1, result.returncode)
            self.assertIn("不一致", result.stderr)
            self.assertFalse(os.path.exists(os.path.join(prod, "X", "good")))

    def test_matching_manifest_promotes_and_records_hashes(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, prod, _, env = self._compliant_fixture(tmp)
            result = subprocess.run(
                [sys.executable, os.path.join(ROOT, "promote.py"), "good"],
                cwd=ROOT, env=env, text=True, capture_output=True, check=False)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            destination = os.path.join(prod, "X", "good")
            self.assertTrue(os.path.isfile(os.path.join(destination, "good.sql")))
            with open(os.path.join(destination, "_promotion.yaml"),
                      encoding="utf-8") as handle:
                promotion = yaml.safe_load(handle)
            self.assertIn("input_hashes", promotion)
            self.assertEqual(
                promotion["rule_version_code"],
                promotion["validation_manifest"]["validation_bundle_code"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
