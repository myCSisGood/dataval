#!/usr/bin/env python3
"""gating/advisory 規則管理工具 — 讓規則維護保持「一條一檔、快速新增」。

    python rules.py new <rule_id>            # 最簡單：新增 Common/gating 規則
    python rules.py new <domain> <gating|advisory> <rule_id>   # 進階：指定位置
    python rules.py new-domain <NAME>        # 建立新 domain 的資料夾骨架（不含規則）
    python rules.py check                    # lint 並 compile（新增後跑這個）
    python rules.py list                     # 盤點目前載入的所有規則
    python rules.py lint                     # 只檢查規則檔語法
    python rules.py compile                  # 只重建 compiled_rules.json
"""
from __future__ import annotations
import importlib.util
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
DOMAIN_ROOT = os.path.join(HERE, "config")
RULES_ROOT = os.path.join(HERE, "config", "Common", "knowhow_py")
TEMPLATES = os.path.join(HERE, "config", "templates")

from dataval.skills import COMMON_DOMAIN, SkillRegistry, VALID_CATEGORIES
from dataval.skills.markdown_skill import load_markdown_skill
from dataval.model import ZONE_GATING, ZONE_ADVISORY


def cmd_list():
    reg = SkillRegistry()
    reg.load_domains(DOMAIN_ROOT, domains=None, rules_root=RULES_ROOT)
    print(f"{'規則 id':36} {'等級':9} {'類別':14} {'domain':8} 檔案")
    print("-" * 100)
    for s in sorted(reg.markdown, key=lambda x: (getattr(x, 'domain', ''), x.id)):
        kind = s.enforcement + ("" if s.check_lines else "(llm)" if s.check_llm else "")
        print(f"{s.id:36} {kind:9} {s.category:14} {getattr(s,'domain','?'):8} "
              f"{os.path.relpath(s.path, HERE)}")
    for m in reg.imperative:
        meta = m.SKILL_META
        print(f"{meta.get('id','?'):36} {'py':9} {meta.get('category','?'):14} "
              f"{meta.get('domain', COMMON_DOMAIN):8} "
              f"config/Common/knowhow_py/{os.path.basename(m.__dict__.get('__file__','') or m.__name__+'.py')}")
    print(f"\n共 {len(reg.markdown)} 條 .md 規則 ＋ {len(reg.imperative)} 條 py 規則")


def cmd_new(domain: str, zone: str, rule_id: str):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", rule_id):
        sys.exit("rule_id 必須是小寫英數底線，例如 order_needs_created_at")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", domain):
        sys.exit("domain 只能包含英數、底線或連字號")
    if zone not in ("gating", "advisory"):
        sys.exit("zone 必須是 gating 或 advisory")
    tpl = os.path.join(TEMPLATES, f"skill_{zone}.template.md")
    dst_dir = os.path.join(DOMAIN_ROOT, domain, "knowhow", zone)
    dst = os.path.join(dst_dir, f"{rule_id}.md")
    if os.path.exists(dst):
        sys.exit(f"已存在：{dst}")
    os.makedirs(dst_dir, exist_ok=True)
    with open(tpl, encoding="utf-8") as f:
        text = f.read()
    defaults = {
        "<唯一代號_小寫英數底線>": rule_id,
        "<structural | naming | best_practice | ssot>": (
            "structural" if zone == "gating" else "best_practice"),
        "<blocking | warning>": "blocking",
    }
    for placeholder, value in defaults.items():
        text = text.replace(placeholder, value)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(text)
    rel = os.path.relpath(dst, HERE)
    print(f"已建立 {rel}")
    print(f"1. 編輯 {rel}")
    print("2. 執行 python rules.py check")
    print("3. 執行 python run.py，在報告查看 SKILL." + rule_id)


def _write_if_absent(path: str, content: str,
                     created: list[str], skipped: list[str]):
    """只在檔案不存在時建立，避免覆蓋既有內容。"""
    if os.path.exists(path):
        skipped.append(os.path.relpath(path, HERE))
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    created.append(os.path.relpath(path, HERE))


def cmd_new_domain(name: str):
    """建立新 domain 的資料夾骨架，符合 domains_layout_test 的佈局契約。

    只搭骨架（naming／erd／flows／ssot／knowhow 空目錄），不含任何治理規則——
    規則仍須用 `rules.py draft`/`rules.py new` 手動撰寫並人審。
    """
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", name):
        sys.exit("domain 名只能包含英數、底線或連字號，且須以字母開頭")
    if name.startswith("_"):
        sys.exit("domain 名不可用 _ 開頭（保留給引擎層）")
    lower = name.lower()
    base = os.path.join(DOMAIN_ROOT, name)
    created: list[str] = []
    skipped: list[str] = []

    glossary = (
        f"# {name} 領域詞彙字典（business glossary）— naming 字典卡控的依據。\n"
        "# 與 Common 合併載入：此處條目會疊加／覆蓋 Common 基底。\n"
        "# 用 SKILL 的 require: term_in_glossary / no_banned_term 對照。\n\n"
        "# 禁用詞 → 建議改用的標準詞（欄位名含左邊的詞就報違規）\n"
        "banned_terms: {}\n\n"
        "# 別名 → 正規詞（同義但非標準的寫法）\n"
        "aliases: {}\n\n"
        "# 本域標準詞白名單（允許出現、不視為違規）\n"
        "standard_terms: []\n")
    erd = (
        f"%% {name} 領域核心參考模型（骨架，請替換為實際實體與關聯）\n"
        "erDiagram\n"
        f'    %% 範例：customer ||--o{{ order : "一位客戶有多筆訂單"\n')
    flow = (
        f"# {name} 領域流程範例（依實際端到端流程替換本檔）\n"
        f"flow: {lower}_sample\n"
        f"title: {name} 範例流程\n"
        "description: 依實際端到端流程替換本檔\n"
        "stages:\n"
        "  - name: 來源系統\n"
        "    kind: source\n"
        f"  - name: {lower}_master\n"
        "    kind: table\n"
        "  - name: 消費端報表\n"
        "    kind: report\n")
    ssot = (
        f"# {name} 域 SSOT registry（範例範本）。與 Common 合併載入：此處的\n"
        "# registry / attribute_owner 條目會疊加／覆蓋 Common。\n"
        "registry: {}         # 例  supplier: {authoritative_table: dim_supplier, key: supplier_no}\n"
        "attribute_owner: {}  # 例  supplier_name: dim_supplier\n")

    _write_if_absent(os.path.join(base, "knowhow", "gating", ".gitkeep"),
                     "", created, skipped)
    _write_if_absent(os.path.join(base, "knowhow", "advisory", ".gitkeep"),
                     "", created, skipped)
    _write_if_absent(os.path.join(base, "naming", "glossary.yaml"),
                     glossary, created, skipped)
    _write_if_absent(os.path.join(base, "erd", f"{lower}_core.mmd"),
                     erd, created, skipped)
    _write_if_absent(os.path.join(base, "flows", "_sample.flow.yaml"),
                     flow, created, skipped)
    _write_if_absent(os.path.join(base, "ssot", "registry.yaml"),
                     ssot, created, skipped)

    if created:
        print(f"✅ 已建立 domain 骨架 config/{name}/：")
        for rel in created:
            print(f"   + {rel}")
    if skipped:
        print("已存在、未覆蓋：")
        for rel in skipped:
            print(f"   = {rel}")
    print("\n這只是資料夾骨架，尚無任何治理規則。實際規則仍需手動撰寫：")
    print(f"   python rules.py new {name} gating <rule_id>        # 新增確定性規則")
    print(f"   python rules.py draft {name} advisory <rule_id> \"<需求>\"  # 由 LLM 起草後人審")
    print("詞彙／SSOT／ERD／flows 內容也請依實際領域知識替換範本佔位。")


def _rule_regexes(sk):
    if sk.applies.get("name_matches"):
        yield "applies_to.name_matches", sk.applies["name_matches"]
    for req in sk.requires:
        if "name_matches" in req:
            yield "require.name_matches", req["name_matches"]["pattern"]
        for key in ("engine_matches", "table_name_matches", "all_columns_name_match"):
            if key in req:
                yield f"require.{key}", req[key]
        if "type_not_for_matching" in req:
            yield "require.type_not_for_matching", req["type_not_for_matching"]["pattern"]


def lint_rules() -> list[str]:
    issues: list[str] = []
    seen_ids: dict[str, str] = {}
    for dirpath, _, files in os.walk(DOMAIN_ROOT):
        # 規則只住在 <域>/knowhow/{gating,advisory}；erd/、flows/、naming/
        # 的 .md（如 README）不是規則,不納入 lint。
        parts = os.path.relpath(dirpath, DOMAIN_ROOT).split(os.sep)
        if len(parts) < 2 or parts[1] != "knowhow":
            continue
        for fn in sorted(files):
            if not fn.endswith(".md"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, HERE)
            try:
                sk = load_markdown_skill(path)
            except Exception as e:
                issues.append(f"{rel}: {e}")
                continue
            with open(path, encoding="utf-8") as f:
                raw = f.read()

            placeholders = sorted(set(re.findall(r"<[^>\n]+>", raw)))
            if placeholders:
                issues.append(f"{rel}: 尚有未填範本內容 → {placeholders}")
            if not re.fullmatch(r"[a-z][a-z0-9_]*", sk.id):
                issues.append(f"{rel}: id 必須符合 [a-z][a-z0-9_]* → {sk.id}")
            if sk.id in seen_ids:
                issues.append(f"{rel}: rule id 重複 {sk.id}（已出現於 {seen_ids[sk.id]}）")
            else:
                seen_ids[sk.id] = rel

            fences = re.findall(r"```(check-llm|check)\s*\n", raw)
            if len(fences) != 1:
                issues.append(f"{rel}: 必須有且只有一個 check/check-llm 區塊，實際 {len(fences)}")
            for heading in ("目的", "適用情境", "違反後果"):
                if not sk.prose.get(heading, "").strip():
                    issues.append(f"{rel}: 缺少必要章節 ## {heading}")

            in_gating = f"{os.sep}gating{os.sep}" in path
            in_advisory = f"{os.sep}advisory{os.sep}" in path
            if not in_gating and not in_advisory:
                issues.append(f"{rel}: 規則必須放在 gating/ 或 advisory/ 目錄")
            if in_gating and sk.zone != ZONE_GATING:
                issues.append(f"{rel}: gating 目錄的規則不得是 advisory")
            if in_advisory and sk.zone != ZONE_ADVISORY:
                issues.append(f"{rel}: advisory 目錄的規則必須是 advisory")
            if sk.check_llm and sk.enforcement != "advisory":
                issues.append(f"{rel}: check-llm 的 enforcement 必須是 advisory")
            if sk.check_lines and sk.enforcement == "advisory":
                issues.append(f"{rel}: 確定性 check 不得使用 advisory enforcement")

            for u in sk.unparsed:
                issues.append(f"{rel}: 卡控語句無法解析 → {u}")
            if not sk.check_lines and not sk.check_llm:
                issues.append(f"{rel}: 沒有任何卡控區塊")
            for label, pattern in _rule_regexes(sk):
                try:
                    re.compile(pattern)
                except re.error as e:
                    issues.append(f"{rel}: {label} regex 無效 /{pattern}/ → {e}")

    for fn in sorted(os.listdir(RULES_ROOT)):
        if not fn.endswith(".py") or fn.startswith("_"):
            continue
        path = os.path.join(RULES_ROOT, fn)
        rel = os.path.relpath(path, HERE)
        try:
            spec = importlib.util.spec_from_file_location(f"lint_{fn[:-3]}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        except Exception as e:
            issues.append(f"{rel}: Python rule 無法載入 → {e}")
            continue
        meta = getattr(mod, "SKILL_META", None)
        if not isinstance(meta, dict):
            issues.append(f"{rel}: 缺少 SKILL_META dict")
            continue
        rule_id = str(meta.get("id", ""))
        domain = str(meta.get("domain", ""))
        if not re.fullmatch(r"[a-z][a-z0-9_]*", rule_id):
            issues.append(f"{rel}: SKILL_META.id 無效 → {rule_id or '(空)'}")
        if rule_id in seen_ids:
            issues.append(f"{rel}: rule id 重複 {rule_id}（已出現於 {seen_ids[rule_id]}）")
        else:
            seen_ids[rule_id] = rel
        if meta.get("category") not in VALID_CATEGORIES:
            issues.append(f"{rel}: category 無效 → {meta.get('category')}")
        if meta.get("zone") not in (ZONE_GATING, ZONE_ADVISORY):
            issues.append(f"{rel}: zone 必須是 gating/advisory")
        if not domain or not os.path.isdir(os.path.join(DOMAIN_ROOT, domain)):
            issues.append(f"{rel}: domain 不存在 → {domain or '(空)'}")
        if meta.get("empty_status", "pass") not in ("pass", "skipped"):
            issues.append(f"{rel}: empty_status 只能是 pass/skipped")
        if not hasattr(mod, "check") and not hasattr(mod, "check_schema"):
            issues.append(f"{rel}: 必須實作 check 或 check_schema")
    return issues


def lint_one(path: str) -> list[str]:
    """對單一草稿檔做與 lint_rules 同標準的檢查（供 adopt 用）。"""
    issues: list[str] = []
    try:
        sk = load_markdown_skill(path)
    except Exception as e:
        return [f"{os.path.basename(path)}: {e}"]
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    placeholders = sorted(set(re.findall(r"<[^>\n]+>", raw)))
    if placeholders:
        issues.append(f"尚有未填範本內容 → {placeholders}")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", sk.id or ""):
        issues.append(f"id 必須符合 [a-z][a-z0-9_]* → {sk.id}")
    fences = re.findall(r"```(check-llm|check)\s*\n", raw)
    if len(fences) != 1:
        issues.append(f"必須有且只有一個 check/check-llm 區塊，實際 {len(fences)}")
    for heading in ("目的", "適用情境", "違反後果"):
        if not sk.prose.get(heading, "").strip():
            issues.append(f"缺少必要章節 ## {heading}")
    if sk.check_llm and sk.enforcement != "advisory":
        issues.append("check-llm 的 enforcement 必須是 advisory")
    if sk.check_lines and sk.enforcement == "advisory":
        issues.append("確定性 check 不得使用 advisory enforcement")
    return issues


def cmd_draft(domain: str, zone: str, rule_id: str, description: str):
    from dataval.drafting import create_draft
    from dataval.llm import from_env
    out, mode = create_draft(os.path.join(HERE, "drafts"), domain, zone,
                             rule_id, description, llm=from_env())
    rel = os.path.relpath(out, HERE)
    if mode == "llm":
        print(f"✍️ 已由 LLM 產出草稿：{rel}")
        print(f"請人工審閱後執行：python rules.py adopt {rule_id}")
    else:
        print(f"✍️ 未接 LLM → 已產出生成請求：{rel}")
        print(f"請 agent 依該檔生成 drafts/{rule_id}.md，"
              f"審閱後執行：python rules.py adopt {rule_id}")


def cmd_adopt(rule_id: str):
    from dataval.drafting import adopt_draft
    dest = adopt_draft(os.path.join(HERE, "drafts"), DOMAIN_ROOT,
                       rule_id, lint_one)
    print(f"✅ 已採用：{os.path.relpath(dest, HERE)}")
    print("下次 python run.py 生效，並自動記入 rules_history/。")


def cmd_lint():
    issues = lint_rules()
    if issues:
        for issue in issues:
            print(f"❌ {issue}")
        print(f"\n{len(issues)} 個問題"); sys.exit(1)
    print("✅ 所有規則檔、ID、metadata、domain 與 regex 正確")


def cmd_compile():
    from dataval.compiler import ensure_compiled
    path, recompiled = ensure_compiled(DOMAIN_ROOT, RULES_ROOT,
                                       os.path.join(HERE, "build", "compiled_rules.json"))
    print(("已重新 compile → " if recompiled else "規則未變，沿用 → ") + os.path.relpath(path, HERE))


def cmd_check():
    """新增或修改規則後的一站式檢查。"""
    cmd_lint()
    cmd_compile()


if __name__ == "__main__":
    if len(sys.argv) >= 6 and sys.argv[1] == "draft":
        cmd_draft(sys.argv[2], sys.argv[3], sys.argv[4],
                  " ".join(sys.argv[5:]))
    elif len(sys.argv) == 3 and sys.argv[1] == "adopt":
        cmd_adopt(sys.argv[2])
    elif len(sys.argv) >= 2 and sys.argv[1] == "compile":
        cmd_compile()
    elif len(sys.argv) >= 2 and sys.argv[1] == "check":
        cmd_check()
    elif len(sys.argv) >= 2 and sys.argv[1] == "list":
        cmd_list()
    elif len(sys.argv) == 3 and sys.argv[1] == "new-domain":
        cmd_new_domain(sys.argv[2])
    elif len(sys.argv) == 3 and sys.argv[1] == "new":
        cmd_new(COMMON_DOMAIN, "gating", sys.argv[2])
    elif len(sys.argv) == 5 and sys.argv[1] == "new":
        cmd_new(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) >= 2 and sys.argv[1] == "lint":
        cmd_lint()
    else:
        print(__doc__)
