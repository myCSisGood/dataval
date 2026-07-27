"""規則版控（rules_history/）。

每次 run.py 啟動時 compile 規則；若規則集與上一版不同，自動在
`rules_history/` 寫入一筆變更紀錄，作為規則的版本控制：

    rules_history/
      CHANGELOG.md                       人讀的變更摘要（最新在最上）
      20260721T043000Z_ff7f187b.json     機器可讀完整快照（自足，可回放）

每筆 JSON 含：
    recorded_at        紀錄時間（UTC）
    rule_version_code  本版規則版本碼（compiled 內容 SHA256 前 16 碼）
    previous_code      上一版規則版本碼（首版為 null）
    added / removed / changed            逐條差異
    rule_count         本版規則總數
    rules              本版完整規則清單（自足快照，不依賴其他檔案）

差異以規則 id 為鍵：新增／移除列出關鍵屬性；修改列出變動的欄位
（如 enforcement 從 warning 改 blocking、卡控條件變更）。

此紀錄與晉升記錄（_promotion.yaml）的規則版本碼同源，
production_audit 的「規則版本碼 drift」可據此追到「差在哪幾條」。
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

#: 比對規則內容時忽略的欄位（純位置資訊，搬檔不算規則變更）
IGNORE_FIELDS = ("file",)


def code_of_text(text: str | None) -> str | None:
    """規則版本碼 = compiled 檔案內容的 SHA256 前 16 碼。
    與 promote.py／production_audit 的 current_rule_code 同源
    （皆以落地檔位元組計算），三處版本碼可互相對照。"""
    if text is None:
        return None
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _strip(rule: dict) -> dict:
    return {k: v for k, v in rule.items() if k not in IGNORE_FIELDS}


def _summary(rule: dict) -> dict:
    return {"id": rule.get("id"), "domain": rule.get("domain"),
            "zone": rule.get("zone"), "category": rule.get("category"),
            "enforcement": rule.get("enforcement"),
            "title": rule.get("title", "")}


def diff_rules(old_payload: dict | None, new_payload: dict) -> dict:
    """回傳 {added, removed, changed}；changed 逐條列出變動欄位。"""
    old_rules = {r["id"]: r for r in (old_payload or {}).get("rules", [])}
    new_rules = {r["id"]: r for r in new_payload.get("rules", [])}
    added = [_summary(new_rules[i]) for i in sorted(new_rules) if i not in old_rules]
    removed = [_summary(old_rules[i]) for i in sorted(old_rules) if i not in new_rules]
    changed = []
    for rid in sorted(set(old_rules) & set(new_rules)):
        before, after = _strip(old_rules[rid]), _strip(new_rules[rid])
        if before == after:
            continue
        fields = {}
        for key in sorted(set(before) | set(after)):
            if before.get(key) != after.get(key):
                fields[key] = {"from": before.get(key), "to": after.get(key)}
        changed.append({**_summary(new_rules[rid]), "fields": fields})
    return {"added": added, "removed": removed, "changed": changed}


def _changelog_entry(record: dict) -> str:
    d = record
    n_add, n_rm, n_ch = (len(d["added"]), len(d["removed"]), len(d["changed"]))
    lines = [f"## {d['recorded_at']} ｜ "
             f"{d['previous_code'] or '（首版）'} → {d['rule_version_code']} ｜ "
             f"➕{n_add} ➖{n_rm} ✏️{n_ch} ｜ 共 {d['rule_count']} 條"]
    for r in d["added"]:
        lines.append(f"- ➕ 新增 `{r['id']}`"
                     f"（{r['domain']}／{r['zone']}／{r['enforcement']}）"
                     f"{'：' + r['title'] if r['title'] else ''}")
    for r in d["removed"]:
        lines.append(f"- ➖ 移除 `{r['id']}`（{r['domain']}／{r['zone']}）")
    for r in d["changed"]:
        keys = "、".join(r["fields"])
        lines.append(f"- ✏️ 修改 `{r['id']}`：{keys}")
    if d.get("implementation_changed"):
        lines.append("- 🧩 驗證引擎／Python rule／依賴版本 bundle 有變更")
    lines.append(f"- 快照：`{d['snapshot_file']}`")
    return "\n".join(lines) + "\n\n"


def record_change(old_text: str | None, new_text: str,
                  history_dir: str) -> str | None:
    """規則集有變時寫入一筆版控紀錄。回傳快照檔路徑；無變化回傳 None。

    old_text / new_text 為 compiled_rules.json 的檔案內容
    （old 為 None 表示首版）。"""
    new_code = code_of_text(new_text)
    old_code = code_of_text(old_text)
    if old_code == new_code:
        return None
    old_payload = json.loads(old_text) if old_text else None
    new_payload = json.loads(new_text)
    delta = diff_rules(old_payload, new_payload)
    if old_payload is not None and not any(delta.values()):
        # 規則內容全同、僅檔案位置等中性差異 → 仍記一筆（版本碼已變，需可追）
        pass
    os.makedirs(history_dir, exist_ok=True)
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    snapshot_name = f"{stamp}_{new_code[:8]}.json"
    record = {
        "recorded_at": now.isoformat(timespec="seconds"),
        "rule_version_code": new_code,
        "previous_code": old_code,
        "rule_count": len(new_payload.get("rules", [])),
        "added": delta["added"],
        "removed": delta["removed"],
        "changed": delta["changed"],
        "snapshot_file": snapshot_name,
        "rules": new_payload.get("rules", []),
        "implementation": new_payload.get("implementation", {}),
        "implementation_changed": (
            (old_payload or {}).get("implementation") !=
            new_payload.get("implementation")),
    }
    with open(os.path.join(history_dir, snapshot_name), "w",
              encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=1)

    changelog = os.path.join(history_dir, "CHANGELOG.md")
    entry = _changelog_entry(record)
    header = ("# 規則版控（自動維護，最新在最上）\n\n"
              "每次 `run.py` 偵測到規則集變更時自動寫入；"
              "完整快照見同名 `.json`。\n\n")
    existing = ""
    if os.path.isfile(changelog):
        with open(changelog, encoding="utf-8") as f:
            existing = f.read()
        existing = existing.split("\n\n", 2)[-1] if existing.startswith("# ") \
            else existing
    with open(changelog, "w", encoding="utf-8") as f:
        f.write(header + entry + existing)
    return os.path.join(history_dir, snapshot_name)
