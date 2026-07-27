"""輸入前置檢核（pre-flight gate）的守門測試。

守的保證：
  P1 三件必備齊全且一致 → 通過，載入結果可直接餵引擎
  P2 必備件（DDL／relations／context）缺漏/不可解析/不一致 → 不通過（不產報告）
  P2b 樣本為選填：缺樣本或樣本有問題 → 不擋報告，只降為警告並略過該表
  P3 宣告基數與樣本矛盾 → 產出會擋的 Finding（隨報告輸出）
  P4 CSV 轉型慣例（空=NULL、布林、整數/小數、前導零保留字串）
"""
import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from dataval import precheck  # noqa: E402

DDL_TWO_TABLES = """
CREATE TABLE orders (
    order_id UInt64 COMMENT 'id',
    customer_id UInt64 COMMENT 'cust',
    created_at DateTime COMMENT 'c',
    updated_at DateTime COMMENT 'u'
) ENGINE = MergeTree() ORDER BY (order_id);
CREATE TABLE order_items (
    order_item_id UInt64 COMMENT 'id',
    order_id UInt64 COMMENT 'fk',
    created_at DateTime COMMENT 'c',
    updated_at DateTime COMMENT 'u'
) ENGINE = MergeTree() ORDER BY (order_item_id);
"""

CONTEXT_OK = """---
subject: 訂單
domains: [CRM]
business_keys:
  orders: [order_id]
---
## 這個 data subject 是什麼
訂單。
## 粒度
orders 一行 = 一張訂單；order_items 一行 = 一個商品項。
## 用途與消費者
報表。
## 上下游來源
結帳服務。
"""

RELATIONS_OK = """relations:
  - from: order_items.order_id
    to: orders.order_id
    cardinality: "N:1"
    kind: fk
"""


def write(path: str, text: str):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class PrecheckCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir)
        self.ddl = os.path.join(self.dir, "order.sql")
        write(self.ddl, DDL_TWO_TABLES)

    def complete(self):
        write(os.path.join(self.dir, "order.samples", "orders.csv"),
              "order_id,customer_id,created_at,updated_at\n"
              "1,42,2026-07-01T00:00:00,2026-07-01T00:00:00\n"
              "2,57,2026-07-02T00:00:00,2026-07-02T00:00:00\n")
        write(os.path.join(self.dir, "order.samples", "order_items.csv"),
              "order_item_id,order_id\n10,1\n11,1\n12,2\n")
        write(os.path.join(self.dir, "order.relations.yaml"), RELATIONS_OK)
        write(os.path.join(self.dir, "order.context.md"), CONTEXT_OK)


class T_P1_CompleteInputPasses(PrecheckCase):
    def test_pass_and_loaded(self):
        self.complete()
        r = precheck.run_precheck(self.ddl)
        self.assertTrue(r.passed, [i.detail for i in r.items if not i.ok])
        self.assertEqual({"orders", "order_items"}, set(r.samples))
        self.assertEqual("訂單", r.subject)
        self.assertEqual(["CRM"], r.domains)
        self.assertEqual({"orders": ["order_id"]}, r.business_keys)
        # relations → declared lineage（local 前綴）
        lin = r.lineage_spec["lineage"]["order_items"]
        self.assertEqual({"order_id": "local.orders.order_id"}, lin["columns"])
        self.assertEqual([], r.diagnostics)  # 基數與樣本一致

    def test_single_table_allows_empty_relations(self):
        ddl = os.path.join(self.dir, "solo.sql")
        write(ddl, "CREATE TABLE t (id UInt64 COMMENT 'x') "
                   "ENGINE=MergeTree() ORDER BY (id);")
        write(os.path.join(self.dir, "solo.samples", "t.csv"), "id\n1\n")
        write(os.path.join(self.dir, "solo.relations.yaml"), "relations: []\n")
        write(os.path.join(self.dir, "solo.context.md"),
              "---\nsubject: 單表\n---\n## 粒度\n一行=一筆。\n")
        r = precheck.run_precheck(ddl)
        self.assertTrue(r.passed, [i.detail for i in r.items if not i.ok])


class T_P1b_FolderLayout(unittest.TestCase):
    """標準佈局：input/<名>/<名>.sql ＋ 同層固定檔名。"""

    def test_folder_layout_passes(self):
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root)
        base = os.path.join(root, "order")
        ddl = os.path.join(base, "order.sql")
        write(ddl, DDL_TWO_TABLES)
        write(os.path.join(base, "samples", "orders.csv"),
              "order_id\n1\n2\n")
        write(os.path.join(base, "samples", "order_items.csv"),
              "order_item_id,order_id\n10,1\n11,2\n")
        write(os.path.join(base, "relations.yaml"), RELATIONS_OK)
        write(os.path.join(base, "context.md"), CONTEXT_OK)
        r = precheck.run_precheck(ddl)
        self.assertTrue(r.passed, [i.detail for i in r.items if not i.ok])
        # 固定檔名優先於 <名>.* 前綴
        pieces = precheck.locate_pieces(ddl)
        self.assertTrue(pieces["relations"].endswith(os.sep + "relations.yaml"))


class T_P2_MissingOrBrokenInputBlocks(PrecheckCase):
    def failed_labels(self, r):
        return {i.label for i in r.items if not i.ok}

    def test_missing_everything(self):
        # 樣本為選填：全空時只有兩件必備（關聯、語意描述）擋，樣本不擋。
        r = precheck.run_precheck(self.ddl)
        self.assertFalse(r.passed)
        self.assertEqual({"關聯", "語意描述"}, self.failed_labels(r))
        self.assertTrue(any("samples" in w for w in r.warnings))

    def test_missing_all_samples_still_passes(self):
        # 三件必備齊全、完全沒給 samples/ → 仍通過並產報告。
        self.complete()
        shutil.rmtree(os.path.join(self.dir, "order.samples"))
        r = precheck.run_precheck(self.ddl)
        self.assertTrue(r.passed, [i.detail for i in r.items if not i.ok])
        self.assertEqual({}, r.samples)
        self.assertNotIn("樣本資料", self.failed_labels(r))

    def test_missing_one_table_csv_warns_not_blocks(self):
        # 只涵蓋部分表 → 不擋；有樣本的表照載，缺的表以警告帶過。
        self.complete()
        os.remove(os.path.join(self.dir, "order.samples", "order_items.csv"))
        r = precheck.run_precheck(self.ddl)
        self.assertTrue(r.passed, [i.detail for i in r.items if not i.ok])
        self.assertNotIn("樣本資料", self.failed_labels(r))
        self.assertIn("orders", r.samples)
        self.assertNotIn("order_items", r.samples)
        self.assertTrue(any("order_items" in w for w in r.warnings))

    def test_csv_header_not_in_ddl_warns_not_blocks(self):
        # 提供的 CSV 表頭有 DDL 沒有的欄位 → 該表樣本略過並警告，不擋報告。
        self.complete()
        write(os.path.join(self.dir, "order.samples", "orders.csv"),
              "order_id,ghost_column\n1,x\n")
        r = precheck.run_precheck(self.ddl)
        self.assertTrue(r.passed, [i.detail for i in r.items if not i.ok])
        self.assertNotIn("樣本資料", self.failed_labels(r))
        self.assertNotIn("orders", r.samples)  # 壞掉的表樣本被略過
        self.assertTrue(any("ghost_column" in w for w in r.warnings))

    def test_multi_table_requires_relation(self):
        self.complete()
        write(os.path.join(self.dir, "order.relations.yaml"), "relations: []\n")
        r = precheck.run_precheck(self.ddl)
        self.assertIn("關聯", self.failed_labels(r))

    def test_relation_endpoint_must_exist(self):
        self.complete()
        write(os.path.join(self.dir, "order.relations.yaml"),
              "relations:\n  - from: order_items.order_id\n"
              "    to: ghost.order_id\n    cardinality: \"N:1\"\n")
        r = precheck.run_precheck(self.ddl)
        self.assertIn("關聯", self.failed_labels(r))

    def test_invalid_cardinality(self):
        self.complete()
        write(os.path.join(self.dir, "order.relations.yaml"),
              "relations:\n  - from: order_items.order_id\n"
              "    to: orders.order_id\n    cardinality: \"1:N\"\n")
        r = precheck.run_precheck(self.ddl)
        self.assertIn("關聯", self.failed_labels(r))

    def test_context_missing_grain_section(self):
        self.complete()
        write(os.path.join(self.dir, "order.context.md"),
              "---\nsubject: 訂單\n---\n## 這個 data subject 是什麼\n訂單。\n")
        r = precheck.run_precheck(self.ddl)
        self.assertIn("語意描述", self.failed_labels(r))

    def test_business_key_value_must_be_nonempty_list(self):
        self.complete()
        write(os.path.join(self.dir, "order.context.md"),
              CONTEXT_OK.replace("orders: [order_id]", "orders: order_id"))
        r = precheck.run_precheck(self.ddl)
        self.assertIn("語意描述", self.failed_labels(r))

    def test_business_key_table_and_columns_must_exist(self):
        self.complete()
        invalid = CONTEXT_OK.replace(
            "orders: [order_id]", "ghost: [id]\n  orders: [missing_id]")
        write(os.path.join(self.dir, "order.context.md"), invalid)
        r = precheck.run_precheck(self.ddl)
        self.assertIn("語意描述", self.failed_labels(r))


class T_P3_CardinalityVsSample(PrecheckCase):
    def test_declared_n1_but_duplicated_one_side_blocks(self):
        self.complete()
        # 「1 的一方」orders.order_id 樣本出現重複 → 宣告與樣本矛盾
        write(os.path.join(self.dir, "order.samples", "orders.csv"),
              "order_id,customer_id\n1,42\n1,57\n")
        r = precheck.run_precheck(self.ddl)
        self.assertTrue(r.passed)  # precheck 本身通過，矛盾以會擋 Finding 交報告
        ids = [f.check_id for f in r.diagnostics]
        self.assertIn("RELATION.CARDINALITY_SAMPLE", ids)
        self.assertTrue(all(f.status == "fail" and f.zone == "gating"
                            for f in r.diagnostics))


class T_P4_CsvCoercion(unittest.TestCase):
    def test_conventions(self):
        c = precheck._coerce
        self.assertIsNone(c(""))                 # 空 = NULL
        self.assertIs(True, c("true"))
        self.assertIs(False, c("False"))
        self.assertEqual(42, c("42"))
        self.assertEqual(19.99, c("19.99"))
        self.assertEqual("0001001", c("0001001"))  # 前導零 = 編碼，保留字串
        self.assertEqual("2026-07-01T00:00:00", c("2026-07-01T00:00:00"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
