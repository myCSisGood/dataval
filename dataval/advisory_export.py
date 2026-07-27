"""顧問區補完橋接。

run.py 是獨立子程序、不繼承 opencode 的 LLM，所以「需要 LLM 的顧問區檢查」
在 Python 端只會標成「待補完」。本模組產出一份給 agent 的指示 + 結構化待補清單，
agent 用它自己的 LLM 產生建議、寫成 <名>.advisory_result.json，再跑一次
`python merge_advisory.py` 把結果合併進報告（含 HTML）。

流程：
  run.py           → reports/<名>.report.{md,json}（確定性檢查結果）
                   → reports/<名>.advisory_prompt.md（給 agent 的指示＋schema）
  agent（用 LLM）  → reports/<名>.advisory_result.json（產生的建議）
  merge_advisory   → 重繪 HTML/MD/JSON，顧問區填入真實建議
"""
from __future__ import annotations
import json
import re
from .model import Schema

_INSTRUCTIONS = """\
# 顧問區補完任務（給 opencode agent）

Python 端沒有 LLM 連線，以下顧問區項目需要你用你的 LLM 完成。
顧問區一律**只提示、永不影響合規判定**。請用繁體中文，措辭為「給設計者思考的提問」，不要下結論。

## 你要做的事

1. 依下方 schema 與情境，針對這三個面向產生建議：
   - **命名語意**：跨表縮寫不一致、同概念異名、欄名與型別語意不符。
   - **主體性概念**：每張表代表的業務主體是否抓對、粒度是否合理、主體間關係建模是否恰當。
   - **各 domain 語意 skill**：見下方 pending_skills 列出的每條，依其描述產生建議。

2. 把結果寫成 JSON 檔：`reports/{name}.advisory_result.json`，格式：
```json
{{
  "naming_semantic": [
    {{"target": "表或表.欄位", "message": "給設計者的提問", "rationale": "為什麼"}}
  ],
  "concept": [
    {{"target": "表名", "message": "主體性提問", "rationale": "為什麼"}}
  ],
  "skills": {{
    "<skill_id>": [
      {{"target": "表或欄位", "message": "提問", "rationale": "為什麼"}}
    ]
  }}
}}
```
此檔案必須符合 `config/_engine/advisory_result.schema.json`；合併前會強制驗證。

3. 跑一次合併，把建議填進報告與 HTML：
```
python merge_advisory.py
```

完成後 reports/{name}.report.html 的顧問區就會顯示真實建議，而非「待補完」。

## 待補的語意 skill（pending_skills）
{pending_skills}

## 未登錄主體候選
{unregistered_candidates}

## schema 與情境
{schema_json}
"""


def build_advisory_prompt(schema: Schema, context: str,
                          name: str = "", pending_skills: list | None = None,
                          unregistered_candidates: list | None = None) -> str:
    payload = {
        "context": context,
        "tables": [
            {
                "name": t.name,
                "primary_key": t.primary_key,
                "sorting_key": t.sorting_key,
                "business_key": t.business_key,
                "business_key_source": t.business_key_source,
                "columns": [
                    {"name": c.name, "type": c.base_type,
                     "nullable": c.nullable, "comment": c.comment}
                    for c in t.columns
                ],
            }
            for t in schema.tables
        ],
    }
    ps = pending_skills or []
    ps_txt = "\n\n".join(
        f"### `{s['id']}` · {s.get('domain', 'Common')} · {s['title']}\n"
        f"{s['desc']}" for s in ps) or "（無）"
    return _INSTRUCTIONS.format(
        name=name or "<名>",
        pending_skills=ps_txt,
        unregistered_candidates=json.dumps(
            unregistered_candidates or [], ensure_ascii=False, indent=2),
        schema_json=json.dumps(payload, ensure_ascii=False, indent=2))


# 權威來源：這裡的規則同時存在於三處，改一處必須同步另外兩處，否則會漂移：
#   1. 本函式（合併程式實際執行的驗證）
#   2. _INSTRUCTIONS 內嵌的「驗證規則」條列（給 agent 看的說明）
#   3. config/_engine/advisory_result.schema.json（JSON Schema 形式，供外部工具參照）
# 目前只有本函式會被程式讀取；schema 檔與 prompt 文字都只是說明用。
def validate_advisory_result(result) -> list[str]:
    """Validate the advisory payload against advisory_result.schema.json semantics.

    Kept dependency-free so the offline governance path remains runnable.
    """
    errors: list[str] = []
    if not isinstance(result, dict):
        return ["最外層必須是 JSON object"]
    required = {"naming_semantic", "concept", "skills"}
    missing = required - set(result)
    extra = set(result) - required
    if missing:
        errors.append(f"缺少必要欄位：{sorted(missing)}")
    if extra:
        errors.append(f"不允許的欄位：{sorted(extra)}")

    def validate_suggestions(value, path):
        if not isinstance(value, list):
            errors.append(f"{path} 必須是 array")
            return
        for index, item in enumerate(value):
            item_path = f"{path}[{index}]"
            if not isinstance(item, dict):
                errors.append(f"{item_path} 必須是 object")
                continue
            expected = {"target", "message", "rationale"}
            if set(item) != expected:
                errors.append(f"{item_path} 欄位必須剛好是 {sorted(expected)}")
            for key in expected:
                if not isinstance(item.get(key), str) or not item.get(key, "").strip():
                    errors.append(f"{item_path}.{key} 必須是非空字串")

    if "naming_semantic" in result:
        validate_suggestions(result["naming_semantic"], "naming_semantic")
    if "concept" in result:
        validate_suggestions(result["concept"], "concept")
    skills = result.get("skills")
    if skills is not None:
        if not isinstance(skills, dict):
            errors.append("skills 必須是 object")
        else:
            for skill_id, suggestions in skills.items():
                if not re.fullmatch(r"[a-z][a-z0-9_]*", str(skill_id)):
                    errors.append(f"skills rule id 無效：{skill_id}")
                validate_suggestions(suggestions, f"skills.{skill_id}")
    return errors
