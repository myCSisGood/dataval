"""規則版控（rules_history）的守門測試。

守的保證：
  H1 首版寫入基線（previous_code 為 None，全數列為新增）
  H2 新增／移除／修改被正確分類；修改列出欄位級 from→to
  H3 規則未變 → 不寫入任何紀錄
  H4 版本碼與 promote.py／production_audit 的計碼同源（檔案內容 SHA256）
  H5 CHANGELOG 最新在最上
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dataval import rules_history  # noqa: E402


def payload(rules):
    return json.dumps({"format": "dataval.compiled_rules.v3",
                       "rule_count": len(rules), "rules": rules,
                       "domains": ["Common"]}, ensure_ascii=False)


def rule(rid, enforcement="warning", **extra):
    base = {"id": rid, "domain": "Common", "zone": "gating",
            "category": "structural", "enforcement": enforcement,
            "title": f"規則 {rid}", "file": f"Common/knowhow/gating/{rid}.md"}
    base.update(extra)
    return base


class HistoryCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)

    def latest_snapshot(self):
        snaps = sorted(f for f in os.listdir(self.dir) if f.endswith(".json"))
        with open(os.path.join(self.dir, snaps[-1]), encoding="utf-8") as f:
            return json.load(f)


class T_H1_Baseline(HistoryCase):
    def test_first_version_records_all_as_added(self):
        text = payload([rule("a"), rule("b")])
        path = rules_history.record_change(None, text, self.dir)
        self.assertIsNotNone(path)
        d = self.latest_snapshot()
        self.assertIsNone(d["previous_code"])
        self.assertEqual({"a", "b"}, {r["id"] for r in d["added"]})
        self.assertEqual(2, d["rule_count"])
        self.assertEqual(2, len(d["rules"]))  # 快照自足


class T_H2_Diff(HistoryCase):
    def test_added_removed_changed(self):
        old = payload([rule("keep"), rule("gone"),
                       rule("mod", enforcement="warning")])
        new = payload([rule("keep"), rule("fresh"),
                       rule("mod", enforcement="blocking")])
        rules_history.record_change(old, new, self.dir)
        d = self.latest_snapshot()
        self.assertEqual(["fresh"], [r["id"] for r in d["added"]])
        self.assertEqual(["gone"], [r["id"] for r in d["removed"]])
        self.assertEqual(["mod"], [r["id"] for r in d["changed"]])
        self.assertEqual({"from": "warning", "to": "blocking"},
                         d["changed"][0]["fields"]["enforcement"])

    def test_file_move_only_is_not_a_rule_change(self):
        old_rules = [rule("a")]
        moved = [dict(rule("a"), file="Common/other/place/a.md")]
        delta = rules_history.diff_rules(
            json.loads(payload(old_rules)), json.loads(payload(moved)))
        self.assertEqual([], delta["changed"])  # 搬檔不算規則變更


class T_H3_NoChangeNoEntry(HistoryCase):
    def test_identical_text_records_nothing(self):
        text = payload([rule("a")])
        self.assertIsNone(rules_history.record_change(text, text, self.dir))
        self.assertEqual([], os.listdir(self.dir))


class T_H4_CodeParity(unittest.TestCase):
    def test_code_matches_audit_and_promotion_source(self):
        from dataval.prodgraph import current_rule_code
        text = payload([rule("a")])
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False,
                                         encoding="utf-8") as f:
            f.write(text)
            tmp = f.name
        try:
            self.assertEqual(current_rule_code(tmp),
                             rules_history.code_of_text(text))
        finally:
            os.unlink(tmp)


class T_H5_ChangelogOrder(HistoryCase):
    def test_newest_entry_on_top(self):
        v1 = payload([rule("a")])
        v2 = payload([rule("a"), rule("b")])
        rules_history.record_change(None, v1, self.dir)
        rules_history.record_change(v1, v2, self.dir)
        with open(os.path.join(self.dir, "CHANGELOG.md"),
                  encoding="utf-8") as f:
            text = f.read()
        self.assertLess(text.index("➕1"), text.index("➕1 ➖0 ✏️0 ｜ 共 1 條")
                        if "共 1 條" in text else len(text))
        # 第二版(共 2 條)的段落必須在第一版(共 1 條)之前
        self.assertLess(text.index("共 2 條"), text.index("共 1 條"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
