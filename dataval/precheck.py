"""輸入前置檢核（pre-flight gate）。

一個 data subject 的輸入（以 <名>.sql 為錨）：
    input/<名>/<名>.sql           DDL              ← 必備
    input/<名>/relations.yaml     表間關聯（含 cardinality） ← 必備
    input/<名>/context.md         語意描述（front-matter＋段落，「粒度」必填）← 必備
    input/<名>/samples/<表>.csv   樣本資料（每表一份） ← 選填

三件必備輸入（DDL／relations／context）任一不過就不產 report；
樣本為**選填**——沒有樣本仍會產生報告，只是樣本相關檢查（型別對樣本、
join key 編碼一致性、基數實檢）因無資料而略過。

三層檢核：
    1. 存在性   三件必備齊全（樣本可缺）
    2. 可解析性 DDL 可 parse、CSV 表頭可讀、YAML 語法正確、context 有必填段落
    3. 一致性   CSV 欄名 ⊆ DDL 欄位；relations 端點存在；cardinality 值合法

此模組完全確定性、不接 LLM，屬閘門區的前置站。
提供了樣本時，宣告的 cardinality 會拿樣本實檢：宣稱 N:1 / 1:1 但樣本出現重複鍵
→ 產出會擋的 Finding（隨報告輸出，不在 precheck 層攔）。
"""
from __future__ import annotations

import csv
import io
import os
import re
from dataclasses import dataclass, field

import yaml

from .model import Finding, ZONE_GATING
from .parser import parse_ddl

CARDINALITIES = ("1:1", "N:1", "N:M")
KINDS = ("fk", "reference", "lookup")

#: context.md 的段落要求。key = 檢核名；pattern 對 ## 標題做比對。
REQUIRED_SECTIONS = {"粒度": r"粒度|grain"}
RECOMMENDED_SECTIONS = {
    "這個 data subject 是什麼": r"是什麼|what",
    "用途與消費者": r"用途|消費者|usage|consumer",
    "上下游來源": r"上下游|來源|upstream|source",
}


@dataclass
class Item:
    """檢核表上的一列。level: ok | fail。detail 給人看。"""
    label: str
    ok: bool
    detail: str


@dataclass
class PrecheckResult:
    name: str
    passed: bool = True
    items: list[Item] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # ---- 檢核通過後可直接餵給引擎的載入結果 ----
    ddl: str = ""
    samples: dict = field(default_factory=dict)
    relations: list[dict] = field(default_factory=list)
    lineage_spec: dict | None = None
    context_text: str = ""
    subject: str = ""
    domains: list[str] = field(default_factory=list)
    business_keys: dict = field(default_factory=dict)
    diagnostics: list[Finding] = field(default_factory=list)

    def add(self, label: str, ok: bool, detail: str) -> bool:
        self.items.append(Item(label, ok, detail))
        if not ok:
            self.passed = False
        return ok


# ---------------------------------------------------------------- CSV 樣本

_INT_RE = re.compile(r"-?\d+")
_FLOAT_RE = re.compile(r"-?\d+\.\d+")


def _coerce(value: str):
    """CSV 值 → Python 值。慣例：空格子 = NULL；true/false = 布林；
    整數/小數自動轉型；其餘（含 ISO 8601 日期時間）維持字串。"""
    if value == "":
        return None
    stripped = value.strip()
    low = stripped.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if _INT_RE.fullmatch(stripped):
        # 前導零（如 0001001）是編碼不是數字，保留字串讓編碼一致性檢查可運作
        digits = stripped.lstrip("-")
        if len(digits) > 1 and digits.startswith("0"):
            return value
        return int(stripped)
    if _FLOAT_RE.fullmatch(stripped):
        return float(stripped)
    return value


def load_sample_csv(path: str) -> tuple[list[str], list[dict]]:
    """回傳 (表頭, rows)。rows 已轉型。"""
    with open(path, encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        raise ValueError("CSV 沒有內容（至少要有表頭列）")
    header = [h.strip() for h in rows[0]]
    if any(not h for h in header):
        raise ValueError("表頭列有空白欄名")
    out = []
    for line_no, raw in enumerate(rows[1:], start=2):
        if not any(cell.strip() for cell in raw):
            continue  # 跳過整列空白
        if len(raw) > len(header):
            raise ValueError(f"第 {line_no} 列欄數（{len(raw)}）多於表頭（{len(header)}）")
        row = {header[i]: _coerce(raw[i]) for i in range(len(raw))}
        out.append(row)
    return header, out


# ------------------------------------------------------------ relations

_LOCAL_RE = re.compile(r"^([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)$")
_EXTERNAL_RE = re.compile(r"^([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)\.([A-Za-z_][\w]*)$")


def _parse_endpoint(ref: str) -> dict | None:
    """'table.col' → local 端點；'DOMAIN.table.col' → 外部端點。"""
    m = _LOCAL_RE.match(ref or "")
    if m:
        return {"scope": "local", "table": m.group(1), "column": m.group(2)}
    m = _EXTERNAL_RE.match(ref or "")
    if m:
        return {"scope": "external", "domain": m.group(1),
                "table": m.group(2), "column": m.group(3)}
    return None


def relations_to_lineage(relations: list[dict]) -> dict | None:
    """宣告的關聯 → 引擎 declared lineage 格式（含 local 與跨 domain）。"""
    lineage: dict = {}
    for rel in relations:
        src, dst = rel["_from"], rel["_to"]
        if src["scope"] != "local":
            continue  # from 端一定是本次 DDL 的表
        entry = lineage.setdefault(src["table"], {"upstream": [], "columns": {}})
        if dst["scope"] == "local":
            up = {"domain": "local", "table": dst["table"]}
            path = f"local.{dst['table']}.{dst['column']}"
        else:
            up = {"domain": dst["domain"], "table": dst["table"]}
            path = f"{dst['domain']}.{dst['table']}.{dst['column']}"
        if up not in entry["upstream"]:
            entry["upstream"].append(up)
        entry["columns"][src["column"]] = path
    return {"lineage": lineage} if lineage else None


def cardinality_findings(relations: list[dict], samples: dict) -> list[Finding]:
    """宣告基數 vs 樣本實檢。宣稱「1 的一方」在樣本出現重複鍵 → 會擋。"""
    out: list[Finding] = []

    def dup_keys(table: str, column: str) -> list:
        vals = [row.get(column) for row in samples.get(table, [])
                if row.get(column) is not None]
        seen, dups = set(), []
        for v in vals:
            key = str(v)
            if key in seen and v not in dups:
                dups.append(v)
            seen.add(key)
        return dups

    for rel in relations:
        card = rel.get("cardinality")
        src, dst = rel["_from"], rel["_to"]
        label = f"{rel['from']} → {rel['to']}（{card}）"
        sides = []
        if card in ("N:1", "1:1") and dst["scope"] == "local":
            sides.append(dst)
        if card == "1:1" and src["scope"] == "local":
            sides.append(src)
        for side in sides:
            dups = dup_keys(side["table"], side["column"])
            if dups:
                out.append(Finding(
                    "RELATION.CARDINALITY_SAMPLE", "structural", "fail", label,
                    f"宣告基數 {card}，但樣本中 {side['table']}.{side['column']} "
                    f"出現重複值：{dups}。宣告與樣本矛盾。",
                    severity="error", source="rule", zone=ZONE_GATING,
                    expected=f"{side['table']}.{side['column']} 在「1 的一方」樣本內唯一",
                    actual=f"重複值 {dups}",
                    fix="修正 relations.yaml 的 cardinality，或修正樣本/設計。"))
    return out


# ------------------------------------------------------------ context.md

_FRONT_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
_HEADER_RE = re.compile(r"^##\s*(.+?)\s*$", re.M)


def parse_context(text: str) -> tuple[dict, dict[str, str]]:
    """回傳 (front-matter dict, {段落標題: 段落內容})。"""
    meta: dict = {}
    body = text
    m = _FRONT_RE.match(text)
    if m:
        loaded = yaml.safe_load(m.group(1)) or {}
        if not isinstance(loaded, dict):
            raise ValueError("front-matter 根節點必須是 mapping")
        meta = loaded
        body = text[m.end():]
    sections: dict[str, str] = {}
    headers = list(_HEADER_RE.finditer(body))
    for i, h in enumerate(headers):
        end = headers[i + 1].start() if i + 1 < len(headers) else len(body)
        sections[h.group(1)] = body[h.end():end].strip()
    return meta, sections


def _find_section(sections: dict[str, str], pattern: str) -> str | None:
    for title, content in sections.items():
        if re.search(pattern, title, re.I):
            return content
    return None


# ------------------------------------------------------- 佈局定位

def locate_pieces(ddl_path: str) -> dict:
    """定位四件輸入的路徑。

    標準佈局（一 subject 一資料夾）：DDL 的同層放固定檔名
        input/<名>/<名>.sql、samples/、relations.yaml、context.md
    舊式平鋪相容：input/<名>.sql、<名>.samples/、<名>.relations.yaml、<名>.context.md
    固定檔名存在時優先。"""
    base_dir = os.path.dirname(os.path.abspath(ddl_path))
    name = os.path.splitext(os.path.basename(ddl_path))[0]

    def pick(fixed: str, prefixed: str) -> str:
        return fixed if os.path.exists(fixed) else prefixed

    return {
        "name": name,
        "samples": pick(os.path.join(base_dir, "samples"),
                        os.path.join(base_dir, f"{name}.samples")),
        "relations": pick(os.path.join(base_dir, "relations.yaml"),
                          os.path.join(base_dir, f"{name}.relations.yaml")),
        "context": pick(os.path.join(base_dir, "context.md"),
                        os.path.join(base_dir, f"{name}.context.md")),
    }


# ------------------------------------------------------------- 主流程

def run_precheck(ddl_path: str) -> PrecheckResult:
    pieces = locate_pieces(ddl_path)
    name = pieces["name"]
    result = PrecheckResult(name=name)

    # ── ① DDL：存在＋可解析 ─────────────────────────────
    try:
        with open(ddl_path, encoding="utf-8") as f:
            result.ddl = f.read()
    except Exception as e:
        result.add("DDL", False, f"{name}.sql 讀取失敗：{type(e).__name__}: {e}")
        return result
    try:
        schema = parse_ddl(result.ddl)
        tables = {t.name: t for t in schema.tables}
    except Exception as e:
        result.add("DDL", False, f"{name}.sql 無法解析：{type(e).__name__}: {e}")
        return result
    if not tables:
        result.add("DDL", False, f"{name}.sql 解析後沒有任何資料表")
        return result
    result.add("DDL", True, f"{name}.sql（{len(tables)} 張表：{'、'.join(tables)}）")

    # ── ② 樣本資料（選填）：<名>.samples/<表>.csv ────────────────
    # 樣本不是必備。缺樣本、只涵蓋部分表、或某份 CSV 有問題，都不擋報告——
    # 一律降為警告，並把該表的樣本略過（樣本相關檢查對缺樣本的表自然跳過）。
    # 提供且有效的樣本照常餵給引擎（型別對樣本、join key 編碼、基數實檢）。
    samples_dir = pieces["samples"]
    if not os.path.isdir(samples_dir):
        result.add("樣本資料", True, "未提供（選填）；樣本相關檢查略過")
        result.warnings.append(
            "未提供 samples/（選填）；型別對樣本、join key 編碼一致性、"
            "基數實檢因無樣本而略過")
    else:
        csv_files = {os.path.splitext(fn)[0]: os.path.join(samples_dir, fn)
                     for fn in sorted(os.listdir(samples_dir))
                     if fn.lower().endswith(".csv")}
        missing = [t for t in tables if t not in csv_files]
        extra = [n for n in csv_files if n not in tables]
        for tname, path in csv_files.items():
            if tname not in tables:
                continue
            try:
                header, rows = load_sample_csv(path)
            except Exception as e:
                result.warnings.append(
                    f"{tname}.csv 解析失敗，該表樣本略過：{e}")
                continue
            ddl_cols = {c.name for c in tables[tname].columns}
            unknown = [h for h in header if h not in ddl_cols]
            if unknown:
                result.warnings.append(
                    f"{tname}.csv 表頭欄名不在 DDL，該表樣本略過：{unknown}")
                continue
            if not rows:
                result.warnings.append(f"{tname}.csv 只有表頭沒有資料列")
            result.samples[tname] = rows
        if extra:
            result.warnings.append(
                f"samples/ 有 DDL 沒有的表：{extra}（將忽略）")
        uncovered = [t for t in tables if t not in result.samples]
        if uncovered:
            result.warnings.append(
                f"樣本未涵蓋全部表（選填）：{['%s.csv' % t for t in uncovered]}"
                f"——這些表的樣本相關檢查略過")
        if result.samples:
            counts = "、".join(f"{t} {len(r)} 列" for t, r in result.samples.items())
            detail = f"{os.path.basename(samples_dir)}/（{counts}）"
            if uncovered:
                detail += f"；{len(uncovered)}/{len(tables)} 張表未附樣本"
            result.add("樣本資料", True, detail)
        else:
            result.add("樣本資料", True, "有 samples/ 但無可用樣本（選填）")

    # ── ③ 關聯：<名>.relations.yaml ──────────────────────
    rel_path = pieces["relations"]
    if not os.path.isfile(rel_path):
        result.add("關聯", False,
                   "缺 relations.yaml"
                   "（單表 subject 可寫 relations: [] 表示確認過沒有）")
    else:
        try:
            with open(rel_path, encoding="utf-8") as f:
                spec = yaml.safe_load(f) or {}
            if not isinstance(spec, dict) or not isinstance(
                    spec.get("relations"), list):
                raise ValueError("根節點必須含 relations: [...] 清單")
            problems = []
            for i, rel in enumerate(spec["relations"], start=1):
                if not isinstance(rel, dict):
                    problems.append(f"第 {i} 條不是 mapping")
                    continue
                src = _parse_endpoint(str(rel.get("from", "")))
                dst = _parse_endpoint(str(rel.get("to", "")))
                if src is None or dst is None:
                    problems.append(
                        f"第 {i} 條 from/to 格式錯誤"
                        "（本地 table.col 或跨 domain 用 DOMAIN.table.col）")
                    continue
                if src["scope"] != "local":
                    problems.append(f"第 {i} 條 from 必須是本次 DDL 的表（table.col）")
                    continue
                card = rel.get("cardinality")
                if card not in CARDINALITIES:
                    problems.append(
                        f"第 {i} 條 cardinality '{card}' 不合法（限 {'/'.join(CARDINALITIES)}）")
                kind = rel.get("kind", "fk")
                if kind not in KINDS:
                    problems.append(f"第 {i} 條 kind '{kind}' 不合法（限 {'/'.join(KINDS)}）")
                # 端點存在性（一致性層）
                for side, tag in ((src, "from"), (dst, "to")):
                    if side["scope"] != "local":
                        continue  # 跨 domain 端點由引擎對 production 實檢
                    t = tables.get(side["table"])
                    if t is None:
                        problems.append(
                            f"第 {i} 條 {tag} 的表 '{side['table']}' 不在 DDL")
                    elif t.col(side["column"]) is None:
                        problems.append(
                            f"第 {i} 條 {tag} 的欄位 "
                            f"'{side['table']}.{side['column']}' 不在 DDL")
                rel["_from"], rel["_to"] = src, dst
                result.relations.append(rel)
            if not problems and len(tables) > 1 and not result.relations:
                problems.append(
                    "多表 subject 至少要宣告一條表間關聯"
                    "（「沒寫」和「確認沒有」必須可區分）")
            if problems:
                result.relations = []
                result.add("關聯", False, "；".join(problems))
            else:
                result.lineage_spec = relations_to_lineage(result.relations)
                n = len(result.relations)
                result.add("關聯", True,
                           f"{os.path.basename(rel_path)}（{n} 條）" if n else
                           f"{os.path.basename(rel_path)}（明確宣告無關聯）")
        except Exception as e:
            result.add("關聯", False,
                       f"{os.path.basename(rel_path)} 解析失敗：{type(e).__name__}: {e}")

    # ── ④ 語意描述：<名>.context.md ──────────────────────
    ctx_path = pieces["context"]
    if not os.path.isfile(ctx_path):
        result.add("語意描述", False,
                   "缺 context.md（front-matter＋段落，「粒度」必填）")
    else:
        try:
            with open(ctx_path, encoding="utf-8") as f:
                text = f.read()
            meta, sections = parse_context(text)
            problems = []
            subject = str(meta.get("subject") or "").strip()
            if not subject:
                problems.append("front-matter 缺 subject（這個 data subject 的名稱）")
            for label, pattern in REQUIRED_SECTIONS.items():
                content = _find_section(sections, pattern)
                if content is None:
                    problems.append(f"缺「{label}」段落（## 標題）")
                elif not content:
                    problems.append(f"「{label}」段落是空的")
            for label, pattern in RECOMMENDED_SECTIONS.items():
                if _find_section(sections, pattern) is None:
                    result.warnings.append(f"context 建議補「{label}」段落")
            domains = meta.get("domains") or []
            if not (isinstance(domains, list) and
                    all(isinstance(d, str) and d.strip() for d in domains)):
                problems.append("front-matter 的 domains 必須是非空字串 list")
                domains = []
            bkeys = meta.get("business_keys", {})
            if bkeys is None:
                bkeys = {}
            if not isinstance(bkeys, dict):
                problems.append("front-matter 的 business_keys 必須是 table -> columns 對照")
                bkeys = {}
            normalized_bkeys: dict[str, list[str]] = {}
            if isinstance(bkeys, dict):
                for table_name, columns in bkeys.items():
                    table_name = str(table_name)
                    if (not isinstance(columns, list) or not columns or
                            not all(isinstance(column, str) and column.strip()
                                    for column in columns)):
                        problems.append(
                            f"business_keys.{table_name} 必須是非空欄位名稱 list")
                        continue
                    table = tables.get(table_name)
                    if table is None:
                        problems.append(
                            f"business_keys 指向 DDL 不存在的表 '{table_name}'")
                        continue
                    missing_columns = [column for column in columns
                                       if table.col(column) is None]
                    if missing_columns:
                        problems.append(
                            f"business_keys.{table_name} 含 DDL 不存在欄位 "
                            f"{missing_columns}")
                        continue
                    normalized_bkeys[table_name] = list(dict.fromkeys(columns))
            if problems:
                result.add("語意描述", False, "；".join(problems))
            else:
                result.subject = subject
                result.domains = [str(d) for d in domains]
                result.business_keys = normalized_bkeys
                result.context_text = text.strip()
                got = "、".join(sections) or "(無段落)"
                result.add("語意描述", True,
                           f"{os.path.basename(ctx_path)}（subject: {subject}；段落：{got}）")
        except Exception as e:
            result.add("語意描述", False,
                       f"{os.path.basename(ctx_path)} 解析失敗：{type(e).__name__}: {e}")

    # ── 一致性加檢：宣告基數 vs 樣本（產會擋 Finding，不攔 precheck）──
    if result.passed:
        result.diagnostics.extend(
            cardinality_findings(result.relations, result.samples))
    return result


# ------------------------------------------------------------- 輸出

def console_lines(result: PrecheckResult) -> list[str]:
    head = ("✅" if result.passed else "❌") + f" {result.name} — " + (
        "必備輸入齊全，進入驗證" if result.passed else "未達可驗證門檻，不產生報告")
    lines = [head]
    for item in result.items:
        lines.append(f"   {'✅' if item.ok else '❌'} {item.label:　<6}{item.detail}")
    for w in result.warnings:
        lines.append(f"   ⚠️  {w}")
    return lines


def to_markdown(result: PrecheckResult) -> str:
    buf = io.StringIO()
    status = "✅ 通過" if result.passed else "❌ 未通過（不產生報告）"
    buf.write(f"# 輸入前置檢核 — {result.name}\n\n")
    buf.write(f"**結果：{status}**\n\n")
    buf.write("一組 data subject 需要三件必備輸入（DDL／relations／context），"
              "樣本為選填（存在 → 可解析 → 一致，三層檢核）：\n\n")
    buf.write("| 檢核項 | 狀態 | 說明 |\n|---|---|---|\n")
    for item in result.items:
        buf.write(f"| {item.label} | {'✅' if item.ok else '❌'} | {item.detail} |\n")
    if result.warnings:
        buf.write("\n## 提醒（不擋）\n\n")
        for w in result.warnings:
            buf.write(f"- {w}\n")
    if not result.passed:
        buf.write("\n## 需要補齊的輸入格式\n\n")
        buf.write("```text\n")
        buf.write(f"input/{result.name}/\n")
        buf.write(f"  {result.name}.sql        DDL（ClickHouse）        ← 必備\n")
        buf.write("  relations.yaml       表間關聯（from/to/cardinality）← 必備\n")
        buf.write("  context.md           語意描述（「粒度」段落必填）  ← 必備\n")
        buf.write("  samples/<表名>.csv   每張表一份樣本（表頭=欄名）  ← 選填\n")
        buf.write("```\n\n完整格式與範例請見 `input/README.md`。\n")
    return buf.getvalue()
