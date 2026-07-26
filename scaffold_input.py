#!/usr/bin/env python3
"""從一份 DDL 搭出 input/<名>/ 四件套的**骨架**。

    python scaffold_input.py <名> <ddl_path>

它會在 input/<名>/ 建立：
  <名>.sql            複製傳入的 DDL 原檔
  samples/<表>.csv    依欄位型別產生 2 列「明顯是佔位」的假資料
  relations.yaml      有宣告 FK 就轉成候選關聯（基數推測 N:1）；否則 relations: []
  context.md          只填 subject front-matter 與待填的「粒度」段落

**這支工具只搭骨架、不假裝生成可信的治理輸入。** 呼應 AGENTS.md 的鐵則
「不可自行代填樣本或語意描述」：產生的樣本是型別推測的假資料、relations 的
基數未經確認、粒度描述是佔位——這三者在跑 run.py 前都必須由人工替換成真實內容。
"""
from __future__ import annotations
import argparse
import csv
import io
import os
import re
import sys
from datetime import datetime

from dataval.parser import parse_ddl

HERE = os.path.dirname(os.path.abspath(__file__))
INPUT_DIR = os.environ.get("DATAVAL_INPUT_DIR", os.path.join(HERE, "input"))

_NOW_DT = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
_NOW_DATE = datetime.now().strftime("%Y-%m-%d")


def _placeholder(base_type: str, row: int) -> str:
    """依正規化型別產生明顯是佔位的假值。空字串＝NULL（CSV 慣例）。"""
    if base_type == "int":
        return str(row)
    if base_type == "float":
        return f"{row}.0"
    if base_type == "decimal":
        return f"{row}.00"
    if base_type == "datetime":
        return _NOW_DT
    if base_type == "date":
        return _NOW_DATE
    if base_type == "bool":
        return "true" if row % 2 == 1 else "false"
    if base_type == "string":
        return f"sample_{row}"
    # array / map / other：無法安全佔位，留空＝NULL，請人工補。
    return ""


def _sample_csv(table, rows: int = 2) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([c.name for c in table.columns])
    for i in range(1, rows + 1):
        writer.writerow([_placeholder(c.base_type, i) for c in table.columns])
    return buf.getvalue()


def _relations_yaml(schema) -> tuple[str, int]:
    """有 FK 就轉候選關聯；回傳 (yaml文字, 關聯數)。"""
    lines = []
    count = 0
    for table in schema.tables:
        for fk in table.foreign_keys:
            for col, ref_col in zip(fk.columns, fk.ref_columns or fk.columns):
                lines.append(f"  - from: {table.name}.{col}")
                lines.append(f"    to: {fk.ref_table}.{ref_col}")
                lines.append('    cardinality: "N:1"    # 由 FK 推測，務必確認')
                lines.append("    kind: fk")
                lines.append("    note: 由 DDL 的 FOREIGN KEY 推測，請確認方向與基數")
                lines.append("")
                count += 1
    header = ("# 由 scaffold_input.py 依 DDL 的 FOREIGN KEY 推測的候選關聯。\n"
              "# from = 「多」的一方；to = 「一」的一方。基數一律推測為 N:1，\n"
              "# **務必人工確認**方向與基數；跨 domain 端點請改成三段式 DOMAIN.table.col。\n")
    if not count:
        return (header +
                "# 本 DDL 未宣告 FK（ClickHouse 常見）。多表 subject 至少要宣告一條，\n"
                "# 單表或確認過無關聯才留空清單。請依實際 join 關係補齊。\n"
                "relations: []\n"), 0
    return header + "relations:\n" + "\n".join(lines) + "\n", count


def _context_md(name: str) -> str:
    return (
        f"---\n"
        f"subject: {name}\n"
        f"# domains: []          # 選填：要載入的領域規則（Common 恆載入）\n"
        f"# business_keys:        # 選填：各表的業務識別鍵\n"
        f"---\n\n"
        f"## 這個 data subject 是什麼\n\n"
        f"<!-- TODO: 請人工填寫這個 data subject 承載什麼業務事實 -->\n\n"
        f"## 粒度（每張表一行代表什麼）\n\n"
        f"<!-- TODO: 請人工填寫實際粒度描述——粒度不明是資料設計最貴的錯誤 -->\n\n"
        f"## 用途與消費者\n\n"
        f"<!-- TODO: 請人工填寫誰會查、拿來做什麼決策 -->\n\n"
        f"## 上下游來源\n\n"
        f"<!-- TODO: 請人工填寫資料從哪來、會流向哪 -->\n")


def main():
    ap = argparse.ArgumentParser(description="從 DDL 搭 input/<名>/ 四件套骨架")
    ap.add_argument("name", help="data subject 名（＝資料夾名／<名>.sql）")
    ap.add_argument("ddl_path", help="來源 DDL 檔路徑")
    args = ap.parse_args()

    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.name):
        sys.exit("名稱只能包含英數、底線或連字號（作為資料夾與檔名）")
    if not os.path.isfile(args.ddl_path):
        sys.exit(f"找不到 DDL：{args.ddl_path}")

    dest = os.path.join(INPUT_DIR, args.name)
    if os.path.exists(dest):
        sys.exit(f"{os.path.relpath(dest, HERE)} 已存在；請換個名稱或先移除，"
                 f"避免覆蓋既有輸入。")

    with open(args.ddl_path, encoding="utf-8") as f:
        ddl = f.read()
    schema = parse_ddl(ddl)
    if not schema.tables:
        sys.exit("DDL 解析後沒有任何表；請確認這是有效的 CREATE TABLE。")

    os.makedirs(os.path.join(dest, "samples"))
    with open(os.path.join(dest, f"{args.name}.sql"), "w", encoding="utf-8") as f:
        f.write(ddl if ddl.endswith("\n") else ddl + "\n")
    for table in schema.tables:
        with open(os.path.join(dest, "samples", f"{table.name}.csv"),
                  "w", encoding="utf-8") as f:
            f.write(_sample_csv(table))
    relations_text, n_rel = _relations_yaml(schema)
    with open(os.path.join(dest, "relations.yaml"), "w", encoding="utf-8") as f:
        f.write(relations_text)
    with open(os.path.join(dest, "context.md"), "w", encoding="utf-8") as f:
        f.write(_context_md(args.name))

    rel = os.path.relpath(dest, HERE)
    tables = "、".join(t.name for t in schema.tables)
    print(f"✅ 已搭骨架 {rel}/（{len(schema.tables)} 張表：{tables}）")
    print(f"   {args.name}.sql、samples/（每表一份 CSV）、relations.yaml"
          f"（{n_rel} 條候選關聯）、context.md")
    print()
    print("⚠️  這是骨架，不是可信的治理輸入。跑 run.py 前，以下三者都必須由人工替換：")
    print("   1. samples/*.csv —— 目前是依欄位型別推測的假資料（int→1,2；string→sample_N…），"
          "請換成真實、涵蓋典型與邊界值的樣本。")
    print("   2. relations.yaml —— 基數一律推測為 N:1"
          + ("（由 FK 推測）" if n_rel else "（本 DDL 無 FK，已留空清單）")
          + "，方向與基數務必人工確認。")
    print("   3. context.md 「粒度」段落 —— 目前是 TODO 佔位，請逐表寫下「一行代表什麼」。")
    print("完成替換後才跑：python run.py")


if __name__ == "__main__":
    main()
