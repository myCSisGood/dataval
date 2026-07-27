"""規則 compile：把 .md 規則轉成機器可讀的 JSON 中間格式。

.md 是「撰寫格式」（人讀規範＋卡控區塊）；compile 產出的
build/compiled_rules.json 是「執行格式」——結構化、可 diff、可稽核。

關鍵設計：
  1. 同一套解析：JSON 由 SkillSpec（引擎實際執行的解析結果）序列化而來，
     不存在第二套解析器，撰寫與執行永不分歧。
  2. 確定性：內容排序、無時間戳。規則沒變 → JSON 逐字不變。
  3. 可稽核：每條規則以明確的 checking rule ID 識別，不使用指紋或雜湊碼。
  4. 更新偵測：每次重新編譯後直接比對結構化內容，有變更才寫入。
"""
from __future__ import annotations
import json
import hashlib
import importlib.metadata
import os
import re
import sys


class RuleLoadError(RuntimeError):
    """規則檔載入失敗（格式/語法問題），訊息含逐檔原因。"""


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validator_implementation(domain_root: str) -> dict:
    """Hash deterministic validator code and parser dependencies.

    Report rendering and LLM-only helpers are deliberately excluded: changes to
    them cannot alter a gating result. All declarative/Python rule sources and
    built-in checking modules are covered by either rule entries or this map.
    """
    project_root = os.path.dirname(os.path.abspath(domain_root))
    relative_files = [
        "dataval/engine.py",
        "dataval/parser.py",
        "dataval/model.py",
        "dataval/precheck.py",
        "dataval/lineage.py",
        "dataval/production.py",
        "dataval/prodgraph.py",
        "dataval/flows.py",
        "dataval/subject_inference.py",
        "dataval/skills/__init__.py",
        "dataval/skills/markdown_skill.py",
    ]
    files = {
        name: _sha256_file(os.path.join(project_root, *name.split("/")))
        for name in relative_files
        if os.path.isfile(os.path.join(project_root, *name.split("/")))
    }
    dependencies = {}
    for distribution in ("sqlglot", "PyYAML"):
        try:
            dependencies[distribution] = importlib.metadata.version(distribution)
        except importlib.metadata.PackageNotFoundError:
            dependencies[distribution] = "missing"
    return {"files": files, "dependencies": dependencies}


def _control_errors(reg) -> list[str]:
    """Reject invalid gating controls during compile, not only during lint."""
    errors: list[str] = []
    seen: dict[str, str] = {}
    for skill in reg.markdown:
        label = getattr(skill, "path", skill.id)
        if skill.id in seen:
            errors.append(f"{label}: rule id 重複 {skill.id}（已出現於 {seen[skill.id]}）")
        else:
            seen[skill.id] = label
        if skill.unparsed:
            errors.extend(f"{label}: 卡控語句無法解析 → {line}" for line in skill.unparsed)
        if not skill.check_lines and not skill.check_llm:
            errors.append(f"{label}: 沒有任何可執行的卡控區塊")
        patterns = []
        if skill.applies.get("name_matches"):
            patterns.append(("applies_to.name_matches", skill.applies["name_matches"]))
        for requirement in skill.requires:
            if "name_matches" in requirement:
                patterns.append(("require.name_matches", requirement["name_matches"]["pattern"]))
            for key in ("engine_matches", "table_name_matches", "all_columns_name_match"):
                if key in requirement:
                    patterns.append((f"require.{key}", requirement[key]))
            if "type_not_for_matching" in requirement:
                patterns.append(("require.type_not_for_matching",
                                 requirement["type_not_for_matching"]["pattern"]))
        for kind, pattern in patterns:
            try:
                re.compile(pattern)
            except re.error as error:
                errors.append(f"{label}: {kind} regex 無效 /{pattern}/ → {error}")
    for module in reg.imperative:
        rule_id = str(module.SKILL_META.get("id", module.__name__))
        label = module.__file__
        if rule_id in seen:
            errors.append(f"{label}: rule id 重複 {rule_id}（已出現於 {seen[rule_id]}）")
        else:
            seen[rule_id] = label
    return errors


def compile_rules(domain_root: str, rules_root: str) -> dict:
    """Load every domain's skills through the real parser and serialize."""
    from .skills import COMMON_DOMAIN, SkillRegistry
    reg = SkillRegistry()
    reg.load_domains(domain_root, domains=None, rules_root=rules_root)
    if reg.load_errors:
        raise RuleLoadError(
            "有規則檔無法載入（規則壞掉不可靜默跳過，卡控會默默消失）：\n  - "
            + "\n  - ".join(reg.load_errors))
    control_errors = _control_errors(reg)
    if control_errors:
        raise RuleLoadError(
            "規則卡控無法安全編譯（gating 規則採 fail-closed）：\n  - "
            + "\n  - ".join(control_errors))

    rules = []
    for s in reg.markdown:
        entry = {
            "id": s.id,
            "domain": getattr(s, "domain", "?"),
            "zone": s.zone,
            "category": s.category,
            "enforcement": s.enforcement,
            "title": s.title,
            "purpose": s.prose.get("目的", ""),
            "fix_hint": getattr(s, "fix_hint", ""),
            "kind": "check" if s.check_lines else ("check-llm" if s.check_llm else "empty"),
            "applies_to": s.applies,
            "requires": s.requires,
            "check_llm": s.check_llm or "",
            "unparsed": s.unparsed,
            "file": os.path.relpath(
                s.path, domain_root).replace(os.sep, "/"),
        }
        rules.append(entry)
    for m in reg.imperative:
        meta = m.SKILL_META
        entry = {
            "id": meta.get("id", m.__name__),
            "domain": meta.get("domain", COMMON_DOMAIN),
            "zone": meta.get("zone", "gating"),
            "category": meta.get("category", "?"),
            "enforcement": "python",
            "title": (m.__doc__ or "").strip().splitlines()[0] if m.__doc__ else "",
            "kind": "python",
            "source_sha256": _sha256_file(m.__file__),
            "file": os.path.relpath(
                m.__file__, domain_root).replace(os.sep, "/"),
        }
        rules.append(entry)

    rules.sort(key=lambda r: (r["domain"], r["id"]))
    domains = sorted(d for d in os.listdir(domain_root)
                     if os.path.isdir(os.path.join(domain_root, d))
                     and not d.startswith("_"))
    return {
        "format": "dataval.compiled_rules.v3",
        "domains": domains,
        "rule_count": len(rules),
        "rules": rules,
        "implementation": _validator_implementation(domain_root),
    }


def ensure_compiled(domain_root: str, rules_root: str,
                    out_path: str) -> tuple[str, bool]:
    """Compile rules and write only when the structured payload changed."""
    payload = compile_rules(domain_root, rules_root)
    if os.path.isfile(out_path):
        try:
            with open(out_path, encoding="utf-8") as f:
                old = json.load(f)
            if old == payload:
                return out_path, False
        except Exception as e:
            print(f"規則 compile 快取無法讀取，將重建：{type(e).__name__}: {e}",
                  file=sys.stderr)
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=1, sort_keys=True)
    return out_path, True


def require_current_compiled(domain_root: str, rules_root: str,
                             compiled_path: str) -> str:
    """Verify the on-disk bundle without rewriting it.

    Only run.py records rule history, so promotion/audit must not consume a
    pending bundle change by silently updating the compiled file first.
    """
    expected = compile_rules(domain_root, rules_root)
    if not os.path.isfile(compiled_path):
        raise RuleLoadError("缺 build/compiled_rules.json；請先執行 run.py")
    try:
        with open(compiled_path, encoding="utf-8") as handle:
            actual = json.load(handle)
    except Exception as error:
        raise RuleLoadError(
            f"compiled bundle 無法讀取：{type(error).__name__}: {error}") from error
    if actual != expected:
        raise RuleLoadError("驗證 bundle 已變更但尚未由 run.py 編譯與記錄歷史")
    return compiled_path
