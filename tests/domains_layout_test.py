"""config/<domain> 領域佈局的守門測試。

守的保證：
  C1 第一層 = 領域（Common/BLM/SCM/PLM/FCM/CRM），每域四種知識資料夾齊備
  C2 規則從 <域>/knowhow/{gating,advisory} 載入（舊式直掛仍相容）
  C3 詞彙字典按域合併：Common 為基底，請求的域可增補/覆蓋
  C4 E2E 流程載入與 FLOW.CONTEXT 標註；壞檔以 FLOW.SPEC 提醒不擋
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dataval import flows  # noqa: E402
from dataval.engine import load_glossary  # noqa: E402
from dataval.parser import parse_ddl  # noqa: E402
from dataval.skills import SkillRegistry  # noqa: E402

DOMAINS_ROOT = os.path.join(ROOT, "config")
EXPECTED_DOMAINS = {"Common", "BLM", "SCM", "PLM", "FCM", "CRM"}
KNOWLEDGE_FOLDERS = ("knowhow", "naming", "erd", "flows")


def write(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class T_C1_LayoutContract(unittest.TestCase):
    def test_first_level_is_domain_with_knowledge_folders(self):
        found = {d for d in os.listdir(DOMAINS_ROOT)
                 if os.path.isdir(os.path.join(DOMAINS_ROOT, d))}
        self.assertTrue(EXPECTED_DOMAINS <= found, found)
        for dom in EXPECTED_DOMAINS:
            for folder in KNOWLEDGE_FOLDERS:
                self.assertTrue(
                    os.path.isdir(os.path.join(DOMAINS_ROOT, dom, folder)),
                    f"{dom}/{folder}")
        # 每域的 erd 與 flows 都有範例檔可供對照撰寫
        for dom in EXPECTED_DOMAINS:
            erd = os.listdir(os.path.join(DOMAINS_ROOT, dom, "erd"))
            self.assertTrue(any(f.endswith(".mmd") for f in erd), dom)
            flo = os.listdir(os.path.join(DOMAINS_ROOT, dom, "flows"))
            self.assertTrue(any(f.endswith(".flow.yaml") for f in flo), dom)
            self.assertTrue(os.path.isfile(os.path.join(
                DOMAINS_ROOT, dom, "naming", "glossary.yaml")), dom)


class T_C2_KnowhowLoading(unittest.TestCase):
    def test_knowhow_subfolder_is_loaded(self):
        reg = SkillRegistry()
        reg.load_domains(DOMAINS_ROOT, domains=["SCM"])
        ids = set(reg.loaded_rule_ids)
        self.assertIn("SKILL.scm_supplier_baseline", ids)  # SCM knowhow
        self.assertIn("SKILL.structural_order_by", ids)    # Common 恆載入

    def test_legacy_flat_layout_still_loads(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        write(os.path.join(tmp, "Common", "gating", "legacy_rule.md"),
              "---\nid: legacy_rule\ncategory: structural\n"
              "enforcement: warning\n---\n\n# 舊式\n\n## 目的\nx\n"
              "## 適用情境\nx\n## 違反後果\nx\n\n## 卡控\n\n"
              "```check\nrequire: has_order_by\n```\n")
        reg = SkillRegistry()
        reg.load_domains(tmp, domains=None)
        self.assertIn("SKILL.legacy_rule", set(reg.loaded_rule_ids))


class T_C3_GlossaryMerge(unittest.TestCase):
    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cfg)
        write(os.path.join(self.cfg, "Common", "naming",
                           "glossary.yaml"),
              "banned_terms:\n  qty: quantity\naliases:\n  client: customer\n")
        write(os.path.join(self.cfg, "SCM", "naming",
                           "glossary.yaml"),
              "banned_terms:\n  supp: supplier\n"
              "aliases:\n  client: buyer\n")  # 覆蓋 Common 的 client

    def test_common_is_base_and_domain_extends(self):
        g = load_glossary(self.cfg, domains=["SCM"])
        self.assertEqual("quantity", g["banned_terms"]["qty"])   # Common 基底
        self.assertEqual("supplier", g["banned_terms"]["supp"])  # SCM 增補
        self.assertEqual("buyer", g["aliases"]["client"])        # SCM 覆蓋

    def test_unrequested_domain_not_merged(self):
        g = load_glossary(self.cfg, domains=[])
        self.assertNotIn("supp", g["banned_terms"])
        self.assertEqual("customer", g["aliases"]["client"])


class T_C4_Flows(unittest.TestCase):
    DDL = ("CREATE TABLE orders (order_id UInt64 COMMENT 'x') "
           "ENGINE=MergeTree() ORDER BY (order_id);")

    def setUp(self):
        self.cfg = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.cfg)

    def test_flow_context_marks_table_position(self):
        write(os.path.join(self.cfg, "CRM", "flows",
                           "f.flow.yaml"),
              "flow: f\ntitle: 測試流程\nstages:\n"
              "  - name: 來源\n    kind: source\n"
              "  - name: orders\n    kind: table\n"
              "  - name: 報表\n    kind: report\n")
        out = flows.run(parse_ddl(self.DDL), ["CRM"], self.cfg)
        ctx = [f for f in out if f.check_id == "FLOW.CONTEXT"]
        self.assertEqual(1, len(ctx))
        self.assertEqual("orders", ctx[0].target)
        self.assertEqual("advisory", ctx[0].zone)
        self.assertIn("第 2/3 站", ctx[0].message)
        self.assertIn("來源", ctx[0].message)

    def test_broken_flow_file_warns_not_blocks(self):
        write(os.path.join(self.cfg, "Common", "flows",
                           "bad.flow.yaml"), "stages: 不是清單\n")
        out = flows.run(parse_ddl(self.DDL), [], self.cfg)
        spec = [f for f in out if f.check_id == "FLOW.SPEC"]
        self.assertEqual(1, len(spec))
        self.assertEqual("warning", spec[0].status)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class T_C5_ConfigSelfCheck(unittest.TestCase):
    """config 自檢：壞檔不可靜默、不可 traceback。"""

    def test_broken_glossary_becomes_warning_not_crash(self):
        cfg = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, cfg)
        write(os.path.join(cfg, "Common", "naming", "glossary.yaml"),
              "banned_terms: [不是, mapping]\n")
        problems = []
        g = load_glossary(cfg, domains=[], problems=problems)
        self.assertEqual({}, g["banned_terms"])   # 壞檔被略過
        self.assertEqual(1, len(problems))        # 但問題被回報
        self.assertIn("glossary.yaml", problems[0])

    def test_broken_rule_raises_named_error(self):
        from dataval.compiler import RuleLoadError, compile_rules
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        write(os.path.join(root, "Common", "knowhow", "gating", "bad.md"),
              "---\nid: bad\nbad front matter\n")
        with self.assertRaises(RuleLoadError) as ctx:
            compile_rules(root, "")
        self.assertIn("bad.md", str(ctx.exception))  # 訊息指名壞檔
