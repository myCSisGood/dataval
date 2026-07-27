"""Skill loading layer.

A skill = scope + logic + category + severity + rationale. It is NOT a fifth
check category; it loads into one of the existing four (structural | naming |
best_practice | ssot). Two authoring forms (hybrid):

  - Declarative (Markdown + check DSL): domain experts write conditions without
    Python. Deterministic rules run in the GATING zone and can block.
  - Imperative (Python): a function check(schema, table) -> list[Finding] for
    complex logic. Declares its own zone.

Skills are .md spec files (parsed by markdown_skill) plus python skills.
"""
from __future__ import annotations
import importlib.util
import inspect
import json
import os
from ..model import Schema, Finding, ZONE_GATING

VALID_CATEGORIES = {"structural", "naming", "best_practice", "ssot"}
COMMON_DOMAIN = "Common"


def _load_python_skill(path: str):
    """Load one Python skill module, or return None when it has no check."""
    name = os.path.splitext(os.path.basename(path))[0]
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    if hasattr(mod, "SKILL_META") and (
            hasattr(mod, "check") or hasattr(mod, "check_schema")):
        return mod
    return None


class SkillRegistry:
    def __init__(self):
        self.markdown: list = []                       # .md skills (rule or llm)
        self.imperative: list = []  # modules exposing SKILL_META + check()
        self.loaded_domains: list[str] = []
        self.loaded_rule_ids: list[str] = []
        self.load_errors: list[str] = []
        self.requested_domains: list[str] = []
        self.unknown_domains: list[str] = []
        # 完整規則清單（bundle 內所有域的規則，與是否載入無關），供涵蓋率報告使用。
        self.inventory: list[dict] = []
        self.available_domains: list[str] = []

    def load_compiled(self, compiled_path: str, domains: list[str] | None = None,
                      config_dir: str = "config"):
        """從 build/compiled_rules.json 載入規則來執行（整合進主流程的 build 產物）。
        Common 一律載入；未指定 domain 時只載入 Common。
        明確傳入 ["*"] 才載入全部。py 規則也依 manifest domain 過濾。"""
        from .markdown_skill import skill_from_compiled
        with open(compiled_path, encoding="utf-8") as f:
            data = json.load(f)
        requested = [d.strip() for d in (domains or []) if d and d.strip()]
        load_all = any(d.lower() in ("*", "all") for d in requested)
        wanted = {d.lower() for d in requested if d.lower() not in ("*", "all")}
        self.requested_domains = requested
        known = {str(d).lower(): str(d) for d in (data.get("domains") or [])}
        self.unknown_domains = sorted(
            d for d in requested
            if d.lower() not in known and d.lower() not in ("*", "all"))
        common_key = COMMON_DOMAIN.lower()
        self.available_domains = [str(d) for d in (data.get("domains") or [])]
        for e in data.get("rules", []):
            dom = e.get("domain", "?")
            # 先登錄到完整清單（不論本次是否載入），涵蓋率報告才看得到被略過的規則。
            self.inventory.append({
                "id": f"SKILL.{e.get('id', '?')}",
                "domain": dom,
                "zone": e.get("zone", "gating"),
                "kind": e.get("kind", ""),
                "category": e.get("category", ""),
                "title": e.get("title", ""),
                "file": e.get("file", ""),
            })
            if dom.lower() != common_key and not load_all and dom.lower() not in wanted:
                continue
            if e.get("kind") == "python":
                path = os.path.join(config_dir, *e["file"].split("/"))
                mod = _load_python_skill(path)
                if mod is not None:
                    self.imperative.append(mod)
                    self.loaded_rule_ids.append(f"SKILL.{e.get('id', mod.__name__)}")
                continue
            self.markdown.append(skill_from_compiled(e))
            self.loaded_rule_ids.append(f"SKILL.{e['id']}")
        all_domains = data.get("domains") or sorted(
            {e.get("domain") for e in data.get("rules", []) if e.get("kind") != "python"})
        if load_all:
            chosen = list(all_domains)
        else:
            chosen = [d for d in all_domains
                      if d.lower() == common_key or d.lower() in wanted]
            if COMMON_DOMAIN in all_domains and COMMON_DOMAIN not in chosen:
                chosen.append(COMMON_DOMAIN)
        self.loaded_domains = sorted(chosen)
        self.loaded_rule_ids = sorted(set(self.loaded_rule_ids))

    def load_domains(self, domain_root: str, domains: list[str] | None = None,
                     rules_root: str = ""):
        """Load skills from a domain-structured root:

            domain_root/<domain>/{gating,advisory}/*.md

        `Common` is ALWAYS loaded. This authoring/compiler path loads every domain
        when `domains` is None;
        otherwise only the named domains (plus Common). Each .md self-declares
        gating vs advisory via its enforcement/check-block, so the gating/advisory
        subfolders are organisational — the zone still comes from the file.
        """
        from .markdown_skill import load_markdown_skill
        if not domain_root or not os.path.isdir(domain_root):
            return
        all_domains = sorted(
            d for d in os.listdir(domain_root)
            if os.path.isdir(os.path.join(domain_root, d))
            and not d.startswith("_"))   # _engine 等底線資料夾不是 domain
        if domains is None:
            chosen = all_domains
        else:
            wanted = {d.strip().lower() for d in domains if d.strip()}
            chosen = [d for d in all_domains
                      if d.lower() == COMMON_DOMAIN.lower() or d.lower() in wanted]
            if COMMON_DOMAIN in all_domains and COMMON_DOMAIN not in chosen:
                chosen.append(COMMON_DOMAIN)
        self.loaded_domains = chosen
        for dom in chosen:
            dom_path = os.path.join(domain_root, dom)
            # 標準佈局：<域>/knowhow/{gating,advisory}；舊式 <域>/{gating,advisory} 相容
            knowhow = os.path.join(dom_path, "knowhow")
            base = knowhow if os.path.isdir(knowhow) else dom_path
            for sub in ("gating", "advisory"):
                subdir = os.path.join(base, sub)
                if os.path.isdir(subdir):
                    for fn in sorted(os.listdir(subdir)):
                        if fn.endswith(".md"):
                            path = os.path.join(subdir, fn)
                            try:
                                sk = load_markdown_skill(path)
                            except Exception as e:
                                self.load_errors.append(
                                    f"{os.path.join(dom, os.path.relpath(path, dom_path))}"
                                    f"：{type(e).__name__}: {e}")
                                continue
                            sk.domain = dom
                            self.markdown.append(sk)
                            self.loaded_rule_ids.append(f"SKILL.{sk.id}")
        if rules_root and os.path.isdir(rules_root):
            for fn in sorted(os.listdir(rules_root)):
                if fn.endswith(".py") and not fn.startswith("_"):
                    path = os.path.join(rules_root, fn)
                    mod = _load_python_skill(path)
                    if mod is not None:
                        self.imperative.append(mod)
                        self.loaded_rule_ids.append(
                            f"SKILL.{mod.SKILL_META.get('id', mod.__name__)}")
        self.loaded_rule_ids = sorted(set(self.loaded_rule_ids))

    def count(self) -> int:
        return len(self.markdown) + len(self.imperative)

    def run(self, schema: Schema, llm=None, glossary: dict | None = None,
            cfg: dict | None = None) -> list[Finding]:
        out: list[Finding] = []
        ctx = {"cfg": cfg or {}, "glossary": glossary or {}}
        for s in self.markdown:
            out.extend(s.run(schema, llm, glossary))  # rule uses glossary; llm-mode uses llm
        for mod in self.imperative:
            meta = mod.SKILL_META
            found: list[Finding] = []
            # schema-level rule: runs ONCE per schema (cross-table logic)
            if hasattr(mod, "check_schema"):
                found.extend(mod.check_schema(schema, ctx) or [])
            # per-table rule: check(schema, table) or check(schema, table, ctx)
            if hasattr(mod, "check"):
                takes_ctx = len(inspect.signature(mod.check).parameters) >= 3
                for t in schema.tables:
                    found.extend((mod.check(schema, t, ctx) if takes_ctx
                                  else mod.check(schema, t)) or [])
            if not found:
                rule_id = meta.get("id", mod.__name__)
                empty_status = meta.get("empty_status", "pass")
                found.append(Finding(
                    f"SKILL.{rule_id}", meta.get("category", "structural"),
                    empty_status, "(schema)",
                    meta.get("empty_message", f"{rule_id}：已執行，未發現違規。"),
                    severity="info", source="skill",
                    zone=meta.get("zone", ZONE_GATING)))
            for f in found:
                f.source = "skill"
                f.category = meta.get("category", f.category)
                f.zone = meta.get("zone", ZONE_GATING)
                out.append(f)
        return out
