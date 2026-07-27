"""規則起草（drafts/）— 「LLM 幫你寫規則，而不是 LLM 執行檢查」。

分工邊界（不動兩區架構）：
  - LLM 只在【撰寫時】出力：把自然語言需求轉成規則草稿。
  - 草稿必須經過【人審 ＋ lint】才能 adopt 進 config/<域>/knowhow/。
  - 進了 knowhow 之後的【執行】永遠是確定性的，與 LLM 無關。

流程與紀錄（每一步都留在 drafts/ 資料夾）：

    rules.py draft <域> <gating|advisory> <rule_id> "<自然語言描述>"
        ├─ 已接 LLM  → 直接產出 drafts/<rule_id>.md 草稿
        └─ 未接 LLM  → 產出 drafts/<rule_id>.prompt.md，
                       由 agent（opencode/Claude Code）代為生成 drafts/<rule_id>.md
    （人工審閱、修改草稿）
    rules.py adopt <rule_id>
        ├─ lint 通過 → 搬進 config/<域>/knowhow/<區>/，狀態記為 adopted
        └─ lint 失敗 → 留在 drafts/，印出逐項問題

    drafts/
      <rule_id>.md            草稿本體（未生效，引擎不會載入這裡）
      <rule_id>.draft.yaml    草稿履歷：需求描述、來源（llm/agent/人工）、
                              時間、狀態（pending/adopted/rejected）
      LOG.md                  起草台帳（最新在最上）：誰時候起草了什麼、
                              何時 adopt 到哪裡

adopt 之後，下一次 run.py 的規則版控（rules_history/）會自動記到
「規則集新增了這條」——drafts/ 記【怎麼來的】，rules_history/ 記
【何時生效、內容為何】，兩份紀錄以 rule_id 互相對照。
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import yaml

DRAFT_SYSTEM_PROMPT = """你是資料治理規則的撰寫助手。請依使用者的需求描述,
產出一條 dataval 規則的 Markdown 檔。嚴格遵守以下格式,只輸出檔案內容本身,
不要任何前後說明或 ``` 包裹:

---
id: {rule_id}
category: <structural|naming|best_practice|ssot 擇一>
enforcement: {enforcement}
---

# <一句話標題>

## 目的
<為什麼需要這條規則>

## 適用情境
<適用哪些表;若限定表名請說明>

## 違反後果
<不遵守會發生什麼>

## 修正建議
<怎麼改>

## 卡控
{check_section}
"""

CHECK_SECTION_GATING = """```check
<可用動詞(一行一個 require:;applies_to: 可限定表):
 has_column <欄>、column_type <欄> <型>、not_nullable <欄>、
 columns_not_both <欄A> <欄B>、has_primary_key、has_business_key、
 has_order_by、no_nullable_in_key、all_columns_commented、
 column_commented <欄>、engine_matches <pattern>、
 table_name_matches <regex>、all_columns_name_match <regex>、
 type_not_used <型>、type_not_for_matching <名稱regex> <型>、
 lowcardinality_when_present <欄>、datetime_with_timezone、
 identifier_max_length <N>、pk_ends_with <字尾>、
 columns_not_named <a,b,c>、no_banned_term、no_alias_term>
```
若上述動詞表達不了(需跨表比對、需翻樣本資料、需查登記簿),
請不要硬湊;改在檔案最後加一行註解:
<!-- NEEDS_PY: 原因 -->
"""

CHECK_SECTION_ADVISORY = """```check-llm
<給語意檢視的提問指引:說明要檢視什麼、以提問語氣回饋設計者>
```
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _log_prepend(drafts_dir: str, line: str):
    path = os.path.join(drafts_dir, "LOG.md")
    header = "# 規則起草台帳（自動維護，最新在最上）\n\n"
    body = ""
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            text = f.read()
        body = text[len(header):] if text.startswith(header) else text
    with open(path, "w", encoding="utf-8") as f:
        f.write(header + line.rstrip() + "\n" + body)


def _meta_path(drafts_dir: str, rule_id: str) -> str:
    return os.path.join(drafts_dir, f"{rule_id}.draft.yaml")


def _save_meta(drafts_dir: str, meta: dict):
    with open(_meta_path(drafts_dir, meta["rule_id"]), "w",
              encoding="utf-8") as f:
        yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)


def load_meta(drafts_dir: str, rule_id: str) -> dict | None:
    path = _meta_path(drafts_dir, rule_id)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def build_prompt(rule_id: str, zone: str, description: str) -> tuple[str, str]:
    """回傳 (system, user) 提示。"""
    enforcement = "advisory" if zone == "advisory" else "<blocking|warning 擇一>"
    section = (CHECK_SECTION_ADVISORY if zone == "advisory"
               else CHECK_SECTION_GATING)
    system = DRAFT_SYSTEM_PROMPT.format(
        rule_id=rule_id, enforcement=enforcement, check_section=section)
    return system, f"需求描述：{description}"


def create_draft(drafts_dir: str, domain: str, zone: str, rule_id: str,
                 description: str, llm=None) -> tuple[str, str]:
    """起草。回傳 (產出檔路徑, 模式)；模式為 'llm' 或 'prompt'。"""
    if not re.fullmatch(r"[a-z][a-z0-9_]*", rule_id or ""):
        raise SystemExit("rule_id 必須是小寫英數底線")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", domain or ""):
        raise SystemExit("domain 只能包含英數、底線或連字號")
    if zone not in ("gating", "advisory"):
        raise SystemExit("zone 必須是 gating 或 advisory")
    os.makedirs(drafts_dir, exist_ok=True)
    existing = load_meta(drafts_dir, rule_id)
    if existing and existing.get("status") == "pending":
        raise SystemExit(f"drafts/{rule_id}.md 已有待審草稿；"
                         "請先 adopt 或刪除後再起草。")
    system, user = build_prompt(rule_id, zone, description)
    meta = {"rule_id": rule_id, "domain": domain, "zone": zone,
            "description": description, "created_at": _now(),
            "status": "pending"}
    llm_on = llm is not None and type(llm).__name__ != "NullLLM"
    if llm_on:
        text = (llm.complete(system, user) or "").strip()
        if text.startswith("```"):
            text = text.strip("`").split("\n", 1)[-1]
        out = os.path.join(drafts_dir, f"{rule_id}.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n")
        meta["source"] = "llm"
        mode = "llm"
    else:
        out = os.path.join(drafts_dir, f"{rule_id}.prompt.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"# 規則草稿生成請求 — {rule_id}\n\n"
                    "請依下方 system 指引與需求，直接產出檔案 "
                    f"`drafts/{rule_id}.md`（只含規則內容本身）。\n\n"
                    f"## system\n\n{system}\n\n## 需求\n\n{user}\n")
        meta["source"] = "agent"
        mode = "prompt"
    _save_meta(drafts_dir, meta)
    _log_prepend(drafts_dir,
                 f"- {meta['created_at']} ✍️ 起草 `{rule_id}`"
                 f"（{domain}／{zone}；來源 {meta['source']}）：{description}")
    return out, mode


def adopt_draft(drafts_dir: str, domain_root: str, rule_id: str,
                lint_fn) -> str:
    """人審後採用：lint 通過才搬進 knowhow；失敗則列出問題並留在 drafts。"""
    meta = load_meta(drafts_dir, rule_id)
    if meta is None:
        raise SystemExit(f"找不到 drafts/{rule_id}.draft.yaml；請先 draft。")
    domain = str(meta.get("domain", ""))
    zone = str(meta.get("zone", ""))
    if not re.fullmatch(r"[a-z][a-z0-9_]*", rule_id or ""):
        raise SystemExit("rule_id 必須是小寫英數底線")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", domain):
        raise SystemExit("草稿 domain 無效")
    if zone not in ("gating", "advisory"):
        raise SystemExit("草稿 zone 無效")
    src = os.path.join(drafts_dir, f"{rule_id}.md")
    if not os.path.isfile(src):
        raise SystemExit(f"找不到草稿 drafts/{rule_id}.md"
                         "（若只有 .prompt.md，請先由 agent 生成草稿本體）。")
    with open(src, encoding="utf-8") as f:
        draft_text = f.read()
    if "NEEDS_PY" in draft_text:
        raise SystemExit("草稿標記了 NEEDS_PY：此規則超出宣告式動詞能力，"
                         "請改寫為 knowhow_py 程式式規則後人工放入。")
    problems = lint_fn(src)
    if problems:
        raise SystemExit("草稿未通過 lint，仍留在 drafts/：\n  - "
                         + "\n  - ".join(problems))
    dest_dir = os.path.join(domain_root, domain, "knowhow", zone)
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, f"{rule_id}.md")
    if os.path.isfile(dest):
        raise SystemExit(f"{dest} 已存在，不覆蓋既有規則。")
    os.replace(src, dest)
    meta["status"] = "adopted"
    meta["adopted_at"] = _now()
    meta["adopted_to"] = os.path.relpath(dest, os.path.dirname(domain_root)) \
        .replace(os.sep, "/")
    _save_meta(drafts_dir, meta)
    _log_prepend(drafts_dir,
                 f"- {meta['adopted_at']} ✅ 採用 `{rule_id}` → "
                 f"`{meta['adopted_to']}`（下次 run.py 生效並記入 rules_history）")
    return dest
