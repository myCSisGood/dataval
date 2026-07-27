"""Skill = a governance SPEC document (human-readable) with an extractable,
machine-enforceable control block. This mirrors industry policy-as-code: the
document is the spec; the control is the precise, executable part carved out of it.

File shape (.md):

    ---
    id: txn_amount_needs_currency
    category: best_practice           # structural | naming | best_practice | ssot
    enforcement: blocking             # blocking | warning | advisory
    ---

    # 交易金額必須記錄幣別            <- 人讀規範：標題

    ## 目的                          <- 人讀：這條在治理什麼
    交易表若只記金額不記幣別，跨國情境下金額無法解讀，導致對帳與報表錯誤。

    ## 適用情境                       <- 人讀：什麼時候適用
    任何交易相關表（transaction / billing / subscription）。

    ## 違反後果                       <- 人讀：為什麼要卡
    金額語意不完整，下游無法正確換算與彙總。

    ## 卡控                          <- 機器執行：圈出來的可執行部分
    ```check
    applies_to: name_matches ".*(transaction|billing|subscription).*"
    require: has_column currency
    ```

The prose sections are carried into the report as rationale/context. ONLY the
```check``` block is executed.

Enforcement mapping:
  blocking  -> gating zone, can fail the compliance verdict
  warning   -> gating zone, warns but does not block
  advisory  -> advisory zone, info only (use for semantic/LLM controls)

Two kinds of control block:
  ```check  -> structured, deterministic lines (below). Repeatable; can block.
  ```check-llm -> natural-language control handed to the LLM; advisory only.
"""
from __future__ import annotations
import os
import re
import yaml
from ..model import Schema, Table, Finding, ZONE_GATING, ZONE_ADVISORY
from ..llm import LLMClient, NullLLM, call_json

VALID_CATEGORIES = {"structural", "naming", "best_practice", "ssot"}
ENFORCEMENT = {"blocking", "warning", "advisory"}


def split_front_matter(text: str) -> tuple[dict, str]:
    text = text.lstrip("\ufeff").strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            return (yaml.safe_load(parts[1]) or {}), parts[2].strip()
    return {}, text


def extract_blocks(body: str) -> tuple[list[str], str | None, dict]:
    """Return (check_lines, check_llm_text, prose_sections).
    check_lines: lines inside ```check fences (deterministic control).
    check_llm_text: text inside ```check-llm fence (LLM control), or None.
    prose_sections: {heading: text} for human-readable sections (for the report).
    """
    check_lines: list[str] = []
    check_llm: str | None = None
    # fenced blocks
    for m in re.finditer(r"```(check-llm|check)\s*\n(.*?)```", body, re.DOTALL):
        kind, content = m.group(1), m.group(2)
        if kind == "check":
            for ln in content.splitlines():
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    check_lines.append(ln)
        else:
            check_llm = content.strip()
    # prose: capture "## 目的 / 適用情境 / 違反後果" style sections (minus check)
    prose: dict[str, str] = {}
    no_fences = re.sub(r"```.*?```", "", body, flags=re.DOTALL)
    for m in re.finditer(r"^##\s+(.+?)\n(.*?)(?=^##\s+|\Z)", no_fences, re.DOTALL | re.MULTILINE):
        heading = m.group(1).strip()
        text = m.group(2).strip()
        if text:
            prose[heading] = text
    return check_lines, check_llm, prose


# ---- deterministic control line grammar (inside ```check```) -------------
# Lines look like:  applies_to: name_matches "<regex>"
#                   require: has_column <name>
#                   require: column_type <col> <base_type>
#                   require: not_nullable <col>
#                   require: columns_not_both <a> <b>
#                   require: name_matches <col> <pattern>
def _parse_check(lines: list[str]) -> tuple[dict, list[dict], list[str]]:
    applies: dict = {}
    requires: list[dict] = []
    unparsed: list[str] = []
    for ln in lines:
        m = re.match(r"applies_to:\s*name_matches\s+\"?(.+?)\"?$", ln)
        if m:
            applies["name_matches"] = m.group(1); continue
        m = re.match(r"applies_to:\s*has_column\s+(\S+)$", ln)
        if m:
            applies["has_column"] = m.group(1); continue
        m = re.match(r"require:\s*has_column\s+(\S+)$", ln)
        if m:
            requires.append({"has_column": m.group(1)}); continue
        m = re.match(r"require:\s*column_type\s+(\S+)\s+(\S+)$", ln)
        if m:
            requires.append({"column_type": {"column": m.group(1), "base_type": m.group(2)}}); continue
        m = re.match(r"require:\s*not_nullable\s+(\S+)$", ln)
        if m:
            requires.append({"not_nullable": m.group(1)}); continue
        m = re.match(r"require:\s*columns_not_both\s+(\S+)\s+(\S+)$", ln)
        if m:
            requires.append({"columns_not_both": [m.group(1), m.group(2)]}); continue
        m = re.match(r"require:\s*name_matches\s+(\S+)\s+(\S+)$", ln)
        if m:
            requires.append({"name_matches": {"column": m.group(1), "pattern": m.group(2)}}); continue
        # ---- table-level / ClickHouse-specific verbs ----
        if re.match(r"require:\s*has_primary_key$", ln):
            requires.append({"has_primary_key": True}); continue
        if re.match(r"require:\s*has_business_key$", ln):
            requires.append({"has_business_key": True}); continue
        if re.match(r"require:\s*has_order_by$", ln):
            requires.append({"has_order_by": True}); continue
        if re.match(r"require:\s*no_nullable_in_key$", ln):
            requires.append({"no_nullable_in_key": True}); continue
        if re.match(r"require:\s*all_columns_commented$", ln):
            requires.append({"all_columns_commented": True}); continue
        m = re.match(r"require:\s*engine_matches\s+(\S+)$", ln)
        if m:
            requires.append({"engine_matches": m.group(1)}); continue
        m = re.match(r"require:\s*table_name_matches\s+(\S+)$", ln)
        if m:
            requires.append({"table_name_matches": m.group(1)}); continue
        m = re.match(r"require:\s*column_commented\s+(\S+)$", ln)
        if m:
            requires.append({"column_commented": m.group(1)}); continue
        m = re.match(r"require:\s*type_not_used\s+(\S+)$", ln)
        if m:
            requires.append({"type_not_used": m.group(1)}); continue
        m = re.match(r"require:\s*lowcardinality_when_present\s+(\S+)$", ln)
        if m:
            requires.append({"lowcardinality_when_present": m.group(1)}); continue
        # ---- vocabulary dictionary (glossary) verbs ----
        if re.match(r"require:\s*no_banned_term$", ln):
            requires.append({"no_banned_term": True}); continue
        if re.match(r"require:\s*no_alias_term$", ln):
            requires.append({"no_alias_term": True}); continue
        if re.match(r"require:\s*term_in_glossary$", ln):
            requires.append({"term_in_glossary": True}); continue
        # ---- verbs added for legacy-rule migration ----
        m = re.match(r"require:\s*all_columns_name_match\s+(\S+)$", ln)
        if m:
            requires.append({"all_columns_name_match": m.group(1)}); continue
        m = re.match(r"require:\s*type_not_for_matching\s+(\S+)\s+(\S+)$", ln)
        if m:
            requires.append({"type_not_for_matching": {"pattern": m.group(1),
                                                       "type": m.group(2)}}); continue
        if re.match(r"require:\s*datetime_with_timezone$", ln):
            requires.append({"datetime_with_timezone": True}); continue
        m = re.match(r"require:\s*identifier_max_length\s+(\d+)$", ln)
        if m:
            requires.append({"identifier_max_length": int(m.group(1))}); continue
        m = re.match(r"require:\s*pk_ends_with\s+(\S+)$", ln)
        if m:
            requires.append({"pk_ends_with": m.group(1)}); continue
        m = re.match(r"require:\s*columns_not_named\s+(\S+)$", ln)
        if m:
            requires.append({"columns_not_named": [w.strip().lower() for w in
                                                   m.group(1).split(",") if w.strip()]}); continue
        unparsed.append(ln)
    return applies, requires, unparsed


def _table_matches(t: Table, applies: dict) -> bool:
    if not applies:
        return True
    if "name_matches" in applies and not re.search(applies["name_matches"], t.name):
        return False
    if "has_column" in applies and t.col(applies["has_column"]) is None:
        return False
    return True


def _eval(t: Table, req: dict, glossary: dict | None = None) -> tuple[bool, dict]:
    """回傳 (ok, detail)。detail 含 msg / expected / actual / fix（違規時填）。"""
    glossary = glossary or {}
    def fail(msg, expected="", actual="", fix=""):
        return False, {"msg": msg, "expected": expected, "actual": actual, "fix": fix}
    OK = (True, {})
    if "has_column" in req:
        col = req["has_column"]
        if t.col(col) is not None:
            return OK
        return fail(f"缺少必要欄位 '{col}'", f"表上有欄位 {col}", "欄位不存在",
                    f"新增欄位 {col}")
    if "column_type" in req:
        spec = req["column_type"]; c = t.col(spec["column"])
        if c is None or c.base_type == spec["base_type"]:
            return OK
        return fail(f"欄位 '{spec['column']}' 型別不符",
                    f"{spec['column']} 為 {spec['base_type']}", f"實際 {c.base_type}",
                    f"將 {spec['column']} 改為 {spec['base_type']}")
    if "not_nullable" in req:
        c = t.col(req["not_nullable"])
        if c is None or not c.nullable:
            return OK
        return fail(f"欄位 '{req['not_nullable']}' 不應為 Nullable",
                    "非 Nullable", "Nullable", f"移除 {c.name} 的 Nullable 包裝")
    if "columns_not_both" in req:
        a, b = req["columns_not_both"]
        if not (t.col(a) is not None and t.col(b) is not None):
            return OK
        return fail(f"欄位 '{a}' 與 '{b}' 不應同時存在", f"{a}、{b} 擇一或分表",
                    "兩者並存", "將其中一者移至其權威表，以鍵引用")
    if "name_matches" in req:
        spec = req["name_matches"]; c = t.col(spec["column"])
        if c is None or re.fullmatch(spec["pattern"], c.name) is not None:
            return OK
        return fail(f"欄位 '{spec['column']}' 不符命名樣式",
                    f"符合 /{spec['pattern']}/", c.name, "依樣式重新命名")
    if "has_primary_key" in req:
        if t.primary_key:
            return OK
        return fail("表缺少明確 PRIMARY KEY", "有明確 PRIMARY KEY", "無",
                    "於 DDL 明確指定 PRIMARY KEY；ORDER BY 僅代表排序鍵")
    if "has_business_key" in req:
        if t.business_key:
            return OK
        return fail("表缺少可識別的 business key",
                    "有明確業務識別鍵",
                    f"排序鍵={t.sorting_key or '無'}、PRIMARY KEY={t.primary_key or '無'}",
                    "在 context.md front-matter 的 business_keys 明確宣告業務識別鍵")
    if "has_order_by" in req:
        if t.sorting_key:
            return OK
        return fail("ClickHouse 表缺少 ORDER BY", "有 ORDER BY", "無",
                    "加上 ORDER BY (鍵欄位)")
    if "no_nullable_in_key" in req:
        keys = list(dict.fromkeys(t.primary_key + t.sorting_key + t.business_key))
        bad = [k for k in keys if (t.col(k) and t.col(k).nullable)]
        if not bad:
            return OK
        return fail(f"鍵欄位為 Nullable：{bad}", "鍵欄位非 Nullable", f"{bad} 為 Nullable",
                    f"移除 {bad} 的 Nullable 包裝")
    if "all_columns_commented" in req:
        missing = [c.name for c in t.columns if not c.comment]
        if not missing:
            return OK
        return fail(f"欄位缺少註解：{missing}", "每個欄位都有 COMMENT",
                    f"{len(missing)} 欄無註解 {missing}", "為每個欄位補上 COMMENT '說明'")
    if "column_commented" in req:
        c = t.col(req["column_commented"])
        if c is None or c.comment:
            return OK
        return fail(f"欄位 '{c.name}' 缺少註解", "有 COMMENT", "無",
                    f"為 {c.name} 補上 COMMENT")
    if "engine_matches" in req:
        eng = t.engine or ""
        if re.search(req["engine_matches"], eng) is not None:
            return OK
        return fail("表引擎不符", f"符合 /{req['engine_matches']}/", eng or "(未指定)",
                    "改用 MergeTree 系列引擎")
    if "table_name_matches" in req:
        if re.fullmatch(req["table_name_matches"], t.name) is not None:
            return OK
        return fail("表名不符樣式", f"符合 /{req['table_name_matches']}/", t.name,
                    "依樣式重新命名（snake_case 全小寫）")
    if "type_not_used" in req:
        bad = [c.name for c in t.columns if req["type_not_used"].lower() in c.raw_type.lower()]
        if not bad:
            return OK
        return fail(f"使用了不建議的型別 {req['type_not_used']}：{bad}",
                    f"不使用 {req['type_not_used']}",
                    "；".join(f"{b}:{t.col(b).raw_type}" for b in bad),
                    "數值精確性需求改用 Decimal(P,S)")
    if "lowcardinality_when_present" in req:
        c = t.col(req["lowcardinality_when_present"])
        if c is None or "lowcardinality" in c.raw_type.lower():
            return OK
        return fail(f"欄位 '{c.name}' 未用 LowCardinality", "LowCardinality(String)",
                    c.raw_type, f"改為 {c.name} LowCardinality(String)")
    if "no_banned_term" in req:
        banned = {k.lower(): v for k, v in (glossary.get("banned_terms") or {}).items()}
        hits = [(c.name, tok, banned[tok]) for c in t.columns
                for tok in re.split(r"[_\s]+", c.name.lower()) if tok in banned]
        if not hits:
            return OK
        return fail("欄位用到禁用詞：" + "；".join(f"{n}（'{k}'）" for n, k, _ in hits),
                    "使用字典標準詞", "；".join(f"{n} 含 '{k}'" for n, k, _ in hits),
                    "；".join(f"{n} 改用 '{v}'" for n, k, v in hits))
    if "no_alias_term" in req:
        aliases = {k.lower(): v for k, v in (glossary.get("aliases") or {}).items()}
        hits = [(c.name, tok, aliases[tok]) for c in t.columns
                for tok in re.split(r"[_\s]+", c.name.lower()) if tok in aliases]
        if not hits:
            return OK
        return fail("欄位用到別名：" + "；".join(f"{n}（'{k}'）" for n, k, _ in hits),
                    "使用正規詞", "；".join(f"{n} 用了別名 '{k}'" for n, k, _ in hits),
                    "；".join(f"{n} 改用 '{v}'" for n, k, v in hits))
    if "term_in_glossary" in req:
        standard = {s.lower() for s in (glossary.get("standard_terms") or [])}
        if not standard:
            return OK
        allow = standard | {"id", "at", "by", "no", "code", "name", "type",
                            "created", "updated", "deleted", "is", "has"}
        unknown = [f"{c.name}（'{tok}'）" for c in t.columns
                   for tok in re.split(r"[_\s]+", c.name.lower())
                   if tok and tok not in allow]
        if not unknown:
            return OK
        return fail("欄位用詞不在認可字典：" + "；".join(unknown),
                    "用詞皆在 standard_terms", "；".join(unknown),
                    "改用字典認可的標準詞，或提請把新詞加入字典")
    if "all_columns_name_match" in req:
        pat = req["all_columns_name_match"]
        bad = [c.name for c in t.columns if re.fullmatch(pat, c.name) is None]
        if not bad:
            return OK
        return fail(f"欄位名不符樣式：{bad}", f"符合 /{pat}/", "；".join(bad),
                    "依樣式重新命名（snake_case 全小寫）")
    if "type_not_for_matching" in req:
        spec = req["type_not_for_matching"]
        bad = [c for c in t.columns
               if re.search(spec["pattern"], c.name.lower())
               and spec["type"].lower() in c.base_type.lower()]
        if not bad:
            return OK
        return fail(f"金額類欄位使用了 {spec['type']}：{[c.name for c in bad]}",
                    "金額類欄位為 Decimal(P,S)",
                    "；".join(f"{c.name}:{c.raw_type}" for c in bad),
                    "；".join(f"{c.name} 改為 Decimal(18,2)" for c in bad))
    if "datetime_with_timezone" in req:
        bad = [c.name for c in t.columns
               if c.base_type == "datetime"
               and "'" not in c.raw_type and "tz" not in (c.comment or "").lower()]
        if not bad:
            return OK
        return fail(f"DateTime 未標明時區：{bad}", "DateTime('UTC') 或註解標明時區",
                    "；".join(bad), "改用 DateTime('UTC') 或於 COMMENT 註明時區")
    if "identifier_max_length" in req:
        n = req["identifier_max_length"]
        bad = ([t.name] if len(t.name) > n else []) + \
              [c.name for c in t.columns if len(c.name) > n]
        if not bad:
            return OK
        return fail(f"識別字超過 {n} 字元：{bad}", f"長度 ≤ {n}",
                    "；".join(f"{b}({len(b)})" for b in bad), "縮短命名")
    if "pk_ends_with" in req:
        suf = req["pk_ends_with"]
        keys = t.business_key or t.primary_key
        bad = [k for k in keys if not k.endswith(suf) and k != "id"]
        if not bad:
            return OK
        return fail(f"主鍵欄位未以 '{suf}' 結尾：{bad}", f"鍵名以 {suf} 結尾",
                    "；".join(bad), f"重新命名為 <實體>{suf}")
    if "columns_not_named" in req:
        banned = set(req["columns_not_named"])
        bad = [c.name for c in t.columns if c.name.lower() in banned]
        if not bad:
            return OK
        return fail(f"欄位名使用保留字：{bad}", "避開 SQL 保留字", "；".join(bad),
                    "改名，例如加上語意前綴")
    return True, {}

def _short_rationale(prose: dict) -> str:
    # prefer 目的; fall back to first section
    for key in ("目的", "Purpose", "purpose"):
        if key in prose:
            return prose[key].replace("\n", " ").strip()[:160]
    if prose:
        return next(iter(prose.values())).replace("\n", " ").strip()[:160]
    return ""


class SkillSpec:
    def __init__(self, fm: dict, body: str, path: str):
        self.path = path
        self.id = fm.get("id") or os.path.splitext(os.path.basename(path))[0]
        self.category = fm.get("category")
        self.enforcement = fm.get("enforcement", "warning")
        self.title = None
        if self.category not in VALID_CATEGORIES:
            raise ValueError(f"skill {self.id}: category 必須是 {VALID_CATEGORIES}")
        if self.enforcement not in ENFORCEMENT:
            raise ValueError(f"skill {self.id}: enforcement 必須是 {ENFORCEMENT}")
        mt = re.search(r"^#\s+(.+)$", body, re.MULTILINE)
        self.title = mt.group(1).strip() if mt else self.id

        self.check_lines, self.check_llm, self.prose = extract_blocks(body)
        self.rationale = _short_rationale(self.prose) or self.title
        self.fix_hint = self.prose.get("修正建議", "").replace("\n", " ").strip()
        # zone derived from enforcement; a check-llm control is always advisory
        self.zone = ZONE_ADVISORY if self.enforcement == "advisory" else ZONE_GATING
        if self.check_llm and not self.check_lines:
            self.zone = ZONE_ADVISORY
        self.applies, self.requires, self.unparsed = _parse_check(self.check_lines)

    def _status_for_fail(self) -> str:
        return "fail" if self.enforcement == "blocking" else "warning"

    def run(self, schema: Schema, llm: LLMClient | None = None,
            glossary: dict | None = None) -> list[Finding]:
        out: list[Finding] = []
        # author feedback for unparsed control lines
        for u in self.unparsed:
            out.append(Finding(f"SKILL.{self.id}", self.category, "warning", "(skill)",
                               f"卡控語句無法解析（已略過）：{u}", severity="warning",
                               source="skill", zone=ZONE_GATING,
                               rationale="請使用支援的卡控語法，或改用 ```check-llm。"))
        # deterministic control — 違規給四問結構（期望/實際/修法），通過彙總一筆
        if self.requires:
            sev = "error" if self.enforcement == "blocking" else "warning"
            passed_tables: list[str] = []
            matched_tables: list[str] = []
            for t in schema.tables:
                if not _table_matches(t, self.applies):
                    continue
                matched_tables.append(t.name)
                details = [d for ok, d in (_eval(t, r, glossary) for r in self.requires) if not ok]
                if details:
                    def uniq(key):
                        return "；".join(dict.fromkeys(
                            d[key] for d in details if d.get(key)))
                    out.append(Finding(f"SKILL.{self.id}", self.category,
                                       self._status_for_fail(), t.name,
                                       f"{self.title}：" + "；".join(d["msg"] for d in details),
                                       severity=sev, rationale=self.rationale,
                                       source="skill", zone=self.zone,
                                       expected=uniq("expected"), actual=uniq("actual"),
                                       fix=self.fix_hint or uniq("fix")))
                else:
                    passed_tables.append(t.name)
            if passed_tables:
                out.append(Finding(f"SKILL.{self.id}", self.category, "pass",
                                   f"{len(passed_tables)} 表",
                                   f"{self.title}：{len(passed_tables)} 表全數通過"
                                   f"（{'、'.join(passed_tables)}）",
                                   severity="info", rationale=self.rationale,
                                   source="skill", zone=self.zone))
            if not matched_tables:
                out.append(Finding(f"SKILL.{self.id}", self.category, "skipped",
                                   "(schema)", f"{self.title}：本次沒有符合適用範圍的表。",
                                   severity="info", rationale=self.rationale,
                                   source="skill", zone=self.zone))
        # llm control (advisory)
        if self.check_llm:
            llm = llm or NullLLM()
            if isinstance(llm, NullLLM):
                out.append(Finding(f"SKILL.{self.id}", self.category, "skipped", "(skill)",
                                   f"未接 LLM，略過語意卡控「{self.title}」。", severity="info",
                                   source="llm", zone=ZONE_ADVISORY))
            else:
                system = (f"你是資料治理檢查器。以下是一條規範的卡控描述，請依它檢視 schema，"
                          f"僅輸出 JSON 陣列，每物件含鍵 target、message、rationale。"
                          f"\n規範標題：{self.title}\n卡控描述：\n{self.check_llm}")
                brief = [f"表 {t.name}（business key={t.business_key}、"
                         f"sorting key={t.sorting_key}）：" +
                         ", ".join(f"{c.name}:{c.base_type}" for c in t.columns)
                         for t in schema.tables]
                res = call_json(llm, system, "\n".join(brief))
                if isinstance(res, list):
                    for item in res:
                        out.append(Finding(f"SKILL.{self.id}", self.category, "info",
                                           str(item.get("target", "(schema)")),
                                           str(item.get("message", "")), severity="info",
                                           rationale=str(item.get("rationale", self.rationale)),
                                           source="llm", zone=ZONE_ADVISORY))
                    if not res:
                        out.append(Finding(f"SKILL.{self.id}", self.category, "info",
                                           "(schema)", f"語意卡控「{self.title}」未發現建議。",
                                           severity="info", rationale=self.rationale,
                                           source="llm", zone=ZONE_ADVISORY))
                else:
                    detail = getattr(llm, "last_error", "")
                    message = f"語意卡控「{self.title}」未取得可解析結果。"
                    if detail:
                        message += f" 連線診斷：{detail}"
                    out.append(Finding(f"SKILL.{self.id}", self.category, "skipped",
                                       "(skill)", message,
                                       severity="info", rationale=self.rationale,
                                       source="llm", zone=ZONE_ADVISORY))
        return out


def skill_from_compiled(entry: dict) -> SkillSpec:
    """從 build/compiled_rules.json 的一條 entry 重建可執行的 SkillSpec。
    執行邏輯（run()）與 .md 解析路徑完全共用——compile 是序列化、這裡是反序列化。"""
    s = SkillSpec.__new__(SkillSpec)
    s.path = entry.get("file", "")
    s.id = entry["id"]
    s.category = entry["category"]
    s.enforcement = entry["enforcement"]
    s.title = entry.get("title") or s.id
    s.prose = {"目的": entry.get("purpose", "")}
    s.rationale = (entry.get("purpose", "").replace("\n", " ").strip()[:160]) or s.title
    s.fix_hint = entry.get("fix_hint", "")
    s.zone = entry["zone"]
    s.check_lines = []
    s.check_llm = entry.get("check_llm") or None
    s.applies = entry.get("applies_to") or {}
    s.requires = entry.get("requires") or []
    s.unparsed = entry.get("unparsed") or []
    s.domain = entry.get("domain", "?")
    return s


def load_markdown_skill(path: str) -> SkillSpec:
    with open(path, encoding="utf-8") as f:
        fm, body = split_front_matter(f.read())
    return SkillSpec(fm, body, path)
