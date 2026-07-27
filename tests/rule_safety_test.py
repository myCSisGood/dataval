"""Fail-closed rule authoring and validation-bundle tests."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import rules
from dataval.compiler import RuleLoadError, compile_rules


def write(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


GOOD = """---
id: {rule_id}
category: structural
enforcement: blocking
---
# Test
## 目的
Test.
## 適用情境
All.
## 違反後果
Bad.
## 卡控
```check
{control}
```
"""


class RuleSafetyTest(unittest.TestCase):
    def test_new_uses_the_shipped_engine_template(self):
        with tempfile.TemporaryDirectory() as domain_root:
            with patch.object(rules, "DOMAIN_ROOT", domain_root):
                rules.cmd_new("Common", "gating", "new_safe_rule")
            self.assertTrue(os.path.isfile(os.path.join(
                domain_root, "Common", "knowhow", "gating", "new_safe_rule.md")))

    def test_compile_rejects_unparsed_gating_control(self):
        with tempfile.TemporaryDirectory() as root:
            domain_root = os.path.join(root, "config")
            write(os.path.join(domain_root, "Common", "knowhow", "gating", "bad.md"),
                  GOOD.format(rule_id="bad_rule", control="require: invented_verb x"))
            with self.assertRaises(RuleLoadError):
                compile_rules(domain_root, os.path.join(
                    domain_root, "Common", "knowhow_py"))

    def test_adopt_lint_rejects_unparsed_and_duplicate_ids(self):
        with tempfile.TemporaryDirectory() as root:
            unparsed = os.path.join(root, "unparsed.md")
            write(unparsed, GOOD.format(
                rule_id="unique_but_invalid", control="require: invented_verb x"))
            self.assertTrue(any("無法解析" in issue
                                for issue in rules.lint_one(unparsed)))
            duplicate = os.path.join(root, "duplicate.md")
            write(duplicate, GOOD.format(
                rule_id="structural_order_by", control="require: has_order_by"))
            self.assertTrue(any("已存在" in issue
                                for issue in rules.lint_one(duplicate)))

    def test_python_logic_changes_compiled_bundle(self):
        with tempfile.TemporaryDirectory() as root:
            domain_root = os.path.join(root, "config")
            os.makedirs(os.path.join(domain_root, "Common", "knowhow", "gating"))
            rule_path = os.path.join(domain_root, "Common", "knowhow_py", "logic.py")
            source = """from dataval.model import Finding
SKILL_META = {{"id": "logic", "domain": "Common", "category": "structural", "zone": "gating"}}
def check(schema, table):
    {body}
"""
            write(rule_path, source.format(body="return []"))
            first = compile_rules(domain_root, os.path.dirname(rule_path))
            write(rule_path, source.format(body="return [Finding('X', 'structural', 'pass', table.name, 'ok')]"))
            second = compile_rules(domain_root, os.path.dirname(rule_path))
            first_rule = next(rule for rule in first["rules"] if rule["id"] == "logic")
            second_rule = next(rule for rule in second["rules"] if rule["id"] == "logic")
            self.assertNotEqual(first_rule["source_sha256"], second_rule["source_sha256"])
            self.assertNotEqual(json.dumps(first, sort_keys=True),
                                json.dumps(second, sort_keys=True))

    def test_builtin_validator_change_changes_bundle(self):
        with tempfile.TemporaryDirectory() as root:
            domain_root = os.path.join(root, "config")
            os.makedirs(os.path.join(domain_root, "Common", "knowhow", "gating"))
            engine = os.path.join(root, "dataval", "engine.py")
            write(engine, "version = 1\n")
            first = compile_rules(domain_root, "")
            write(engine, "version = 2\n")
            second = compile_rules(domain_root, "")
            self.assertNotEqual(first["implementation"], second["implementation"])


if __name__ == "__main__":
    unittest.main()
