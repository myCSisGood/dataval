"""Report builder: zone-aware JSON + Markdown.

Verdict rule: only GATING-zone findings with status 'fail' and severity 'error'
block. Advisory findings (LLM and design suggestions) are info only.
"""
from __future__ import annotations
import json
from collections import Counter
from datetime import datetime, timezone
from .model import Finding, ZONE_GATING, ZONE_ADVISORY

CATEGORY_TITLES = {
    "structural": "結構（欄位／型別／約束）",
    "naming": "命名規則",
    "best_practice": "最佳實踐",
    "ssot": "單一真實源（跨域）",
    "concept": "資料設計概念（主體性）",
    "lineage": "Lineage 關聯治理",
}
_ICON = {"pass": "✅", "warning": "⚠️", "fail": "❌", "info": "ℹ️",
         "skipped": "⏭️"}


def _generated_at() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def summarize(findings: list[Finding]) -> dict:
    gating = [f for f in findings if f.zone == ZONE_GATING]
    blocking = [f for f in gating if f.status == "fail" and f.severity == "error"]
    by_status = Counter(f.status for f in findings)
    return {
        "total": len(findings),
        "gating": len(gating),
        "advisory": len(findings) - len(gating),
        "pass": by_status.get("pass", 0),
        "warning": by_status.get("warning", 0),
        "fail": by_status.get("fail", 0),
        "info": by_status.get("info", 0),
        "skipped": by_status.get("skipped", 0),
        "compliant": len(blocking) == 0,
        "blocking_count": len(blocking),
    }


def checking_rule_summary(findings: list[Finding],
                          loaded_rule_ids: list[str] | None = None) -> dict:
    """Summarize the design-level outcome directly by checking rule ID.

    A rule is listed once using the strongest gating outcome it produced:
    failed > warning > passed > not_checked. Advisory IDs are kept separate
    because they never participate in the compliance verdict.
    """
    by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        by_rule.setdefault(f.check_id, []).append(f)

    out = {"passed": [], "warnings": [], "failed": [],
           "not_checked": [], "advisory": []}
    for rule_id, items in sorted(by_rule.items()):
        gating = [f for f in items if f.zone == ZONE_GATING]
        advisory = [f for f in items if f.zone == ZONE_ADVISORY]
        if gating:
            if any(f.status == "fail" and f.severity == "error" for f in gating):
                out["failed"].append(rule_id)
            elif any(f.status in ("warning", "fail") for f in gating):
                out["warnings"].append(rule_id)
            elif any(f.status == "pass" for f in gating):
                out["passed"].append(rule_id)
            else:
                out["not_checked"].append(rule_id)
        if advisory:
            out["advisory"].append(rule_id)
    represented = set().union(*(set(ids) for ids in out.values()))
    out["not_checked"].extend(
        rule_id for rule_id in sorted(set(loaded_rule_ids or []))
        if rule_id not in represented)
    return out


def blocking_summary(findings: list[Finding]) -> dict:
    """依「規則」彙整本次卡控結果：哪些規則把設計卡下來、擋了哪些對象。

    回傳 {"blocked": [...], "warned": [...]}，每項含 rule（check_id）、
    title（從訊息取的規則名）、targets（被擋對象）、reason（違規描述示例）。"""
    def _agg(items):
        by_rule: dict[str, dict] = {}
        for f in items:
            title = f.message.split("：", 1)[0] if "：" in f.message else f.check_id
            reason = f.message.split("：", 1)[1] if "：" in f.message else f.message
            e = by_rule.setdefault(f.check_id, {"rule": f.check_id, "title": title,
                                                "targets": [], "reason": reason})
            if f.target not in e["targets"]:
                e["targets"].append(f.target)
        return sorted(by_rule.values(), key=lambda x: x["rule"])
    gating = [f for f in findings if f.zone == ZONE_GATING]
    return {
        "blocked": _agg([f for f in gating if f.status == "fail" and f.severity == "error"]),
        "warned": _agg([f for f in gating if f.status == "warning"]),
    }


def diff_findings(old: dict, new: dict) -> dict:
    """比對兩份 report 的 findings，回傳 {added, removed, changed}。

    key = (check_id, target)；changed 逐項記錄 status/message 的 from→to。
    只讀 findings，因此 generated_at 等時間戳天生被忽略（不算差異）。
    比對模式沿用 rules_history.diff_rules，只是換 key 與比較欄位。
    """
    def index(payload: dict | None) -> dict:
        out: dict = {}
        for f in (payload or {}).get("findings", []) or []:
            out[(f.get("check_id"), f.get("target"))] = f
        return out

    def brief(f: dict) -> dict:
        return {"check_id": f.get("check_id"), "target": f.get("target"),
                "status": f.get("status"), "zone": f.get("zone"),
                "message": f.get("message")}

    old_i, new_i = index(old), index(new)
    key = lambda k: (str(k[0]), str(k[1]))
    added = [brief(new_i[k]) for k in sorted(new_i, key=key) if k not in old_i]
    removed = [brief(old_i[k]) for k in sorted(old_i, key=key) if k not in new_i]
    changed = []
    for k in sorted(set(old_i) & set(new_i), key=key):
        before, after = old_i[k], new_i[k]
        fields = {}
        for field in ("status", "message"):
            if before.get(field) != after.get(field):
                fields[field] = {"from": before.get(field), "to": after.get(field)}
        if fields:
            changed.append({"check_id": k[0], "target": k[1],
                            "zone": after.get("zone"), "fields": fields})
    return {"added": added, "removed": removed, "changed": changed}


def to_json(findings: list[Finding], meta: dict | None = None,
            deterministic: bool = False) -> str:
    gating = [f.to_dict() for f in findings if f.zone == ZONE_GATING]
    advisory = [f.to_dict() for f in findings if f.zone == ZONE_ADVISORY]
    meta = meta or {}
    payload = {
        "meta": meta,
        "summary": summarize(findings),
        "checking_rule_summary": checking_rule_summary(
            findings, meta.get("checking_rule_ids_loaded")),
        "blocking_summary": blocking_summary(findings),
        "lineage": meta.get("lineage", {}),
        # Two zones kept as separate sections so the deterministic gating result
        # is clearly distinguished from advisory/LLM output. The flat "findings"
        # list is retained for backward compatibility.
        "gating_zone": {
            "note": "確定性檢查，決定合規判定；結果以 checking rule ID 呈現",
            "findings": gating,
        },
        "advisory_zone": {
            "note": "LLM／語意建議，一律 info，永不影響合規判定，不保證可重複",
            "findings": advisory,
        },
        "findings": [f.to_dict() for f in findings],
    }
    # Timestamp is excluded in deterministic mode so the same input yields a
    # byte-identical file (useful for diffing / verifying the gating result).
    if not deterministic:
        payload["generated_at"] = _generated_at()
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def to_markdown(findings: list[Finding], meta: dict | None = None) -> str:
    s = summarize(findings)
    verdict = "✅ 合規" if s["compliant"] else "❌ 不合規"
    meta = meta or {}
    lines = [
        "# 資料設計驗證報告",
        f"_產生時間 {_generated_at()}_<br>",
        f"**判定：{verdict}**（會擋項目 {s['blocking_count']}）<br>",
        f"通過 {s['pass']} · 警告 {s['warning']} · 失敗 {s['fail']} · "
        f"略過 {s['skipped']} · 提示 {s['info']}<br>",
        f"閘門區 {s['gating']} 項 · 顧問區 {s['advisory']} 項<br>",
    ]
    if meta:
        lines.append(f"> 方言 {meta.get('dialect')} · 表數 {meta.get('tables')} "
                     f"· 載入 skill {meta.get('skills_loaded', 0)} 條")
    lines.append("")

    # checking rule ID 總覽：不用指紋，直接呈現各規則的設計級結果。
    crs = checking_rule_summary(findings, meta.get("checking_rule_ids_loaded"))
    lines.append("## Checking rule ID 摘要")
    labels = (("failed", "❌ 擋下"), ("warnings", "⚠️ 警告"),
              ("passed", "✅ 通過"), ("not_checked", "ℹ️ 未實檢／略過"),
              ("advisory", "💡 顧問"))
    for key, label in labels:
        ids = crs[key]
        lines.append(f"- {label}：" + ("、".join(f"`{x}`" for x in ids) if ids else "（無）"))
    lines.append("")

    lineage = meta.get("lineage") or {}
    relationships = lineage.get("relationships") or []
    lines.append("## Lineage 關聯")
    lines.append(f"> {lineage.get('note') or '本次沒有 lineage 資訊。'}")
    lines.append("")
    if relationships:
        lines.append("| 來源 | 目標 | 欄位映射 | 性質 |")
        lines.append("|---|---|---|---|")
        kind_labels = {
            "declared": "YAML 明確宣告",
            "suggested": "系統建議（方向待確認）",
            "suggested-undirected": "系統建議（方向未知）",
            "er-suggested": "ER diagram 建議（方向待確認）",
            "er-undirected": "ER diagram 關聯（方向未知）",
        }
        for relation in relationships:
            mappings = "<br>".join(
                f"`{item.get('source', '')}` → `{item.get('target', '')}`"
                for item in relation.get("columns", []))
            if not mappings:
                mappings = (f"ER 關係：`{relation['label']}`"
                            if relation.get("label") else "（未宣告欄位映射）")
            source = str(relation.get("source", "")).replace("|", "\\|")
            target = str(relation.get("target", "")).replace("|", "\\|")
            kind = ("YAML 宣告＋ER 對應" if relation.get("er_confirmed") else
                    kind_labels.get(relation.get("kind"),
                                    str(relation.get("kind", ""))))
            lines.append(f"| `{source}` | `{target}` | {mappings} | {kind} |")
    else:
        lines.append("（無關聯）")
    lines.append("")

    # 本次卡控摘要 — 依規則描述：這次是被哪幾條規則卡下來的
    bs = blocking_summary(findings)
    if bs["blocked"] or bs["warned"]:
        lines.append("## 本次卡控摘要（被哪些規則卡下來）")
        if bs["blocked"]:
            lines.append("**擋下（不合規的原因）：**")
            for b in bs["blocked"]:
                lines.append(f"- `{b['rule']}` {b['title']} → 擋下 "
                             f"{'、'.join(b['targets'])}（{b['reason'][:60]}）")
        if bs["warned"]:
            lines.append("")
            lines.append("**警告（放行但需注意）：**")
            for b in bs["warned"]:
                lines.append(f"- `{b['rule']}` {b['title']} → "
                             f"{'、'.join(b['targets'])}")
        lines.append("")

    for cat, title in CATEGORY_TITLES.items():
        cat_f = [f for f in findings if f.category == cat]
        if not cat_f:
            continue
        lines.append(f"## {title}")
        cat_f.sort(key=lambda f: (f.status != "fail", f.status != "warning",
                                  f.status != "skipped", f.status != "info"))
        lines.append("")
        lines.append("| | 區 | 檢查 | 對象 | 說明 | 來源 |")
        lines.append("|---|---|---|---|---|---|")
        for f in cat_f:
            zone = "閘門" if f.zone == ZONE_GATING else "顧問"
            msg = f.message.replace("|", "\\|")
            if f.expected or f.actual:
                msg += (f" <br>**期望** {f.expected} ｜ **實際** {f.actual}"
                        ).replace("|", "\\|").replace("\\|｜\\|", "｜")
            if f.fix:
                msg += f" <br>**修法** {f.fix}".replace("|", "\\|")
            if f.rationale:
                msg += f" <br>_理由：{f.rationale}_".replace("|", "\\|")
            lines.append(f"| {_ICON.get(f.status,'')} | {zone} | `{f.check_id}` | "
                         f"`{f.target}` | {msg} | {f.source} |")
        lines.append("")
    return "\n".join(lines)


# ---- HTML report (single self-contained file, lightweight interactivity) ----
import html as _html


def _esc(s) -> str:
    return _html.escape(str(s if s is not None else ""))


def _lineage_html(meta: dict) -> str:
    lineage = meta.get("lineage") or {}
    relationships = lineage.get("relationships") or []
    note = _esc(lineage.get("note") or "本次沒有 lineage 資訊。")
    if not relationships:
        body = '<div class="bs-row"><span class="bs-t">（無關聯）</span></div>'
    else:
        kind_labels = {
            "declared": "YAML 明確宣告",
            "suggested": "系統建議（方向待確認）",
            "suggested-undirected": "系統建議（方向未知）",
            "er-suggested": "ER diagram 建議（方向待確認）",
            "er-undirected": "ER diagram 關聯（方向未知）",
        }
        rows = []
        for relation in relationships:
            mappings = "、".join(
                f"{_esc(item.get('source'))} → {_esc(item.get('target'))}"
                for item in relation.get("columns", []))
            if not mappings:
                mappings = (f"ER 關係：{_esc(relation['label'])}"
                            if relation.get("label") else "未宣告欄位映射")
            kind = ("YAML 宣告＋ER 對應" if relation.get("er_confirmed") else
                    kind_labels.get(relation.get("kind"), relation.get("kind", "")))
            arrow = "↔" if relation.get("kind") in (
                "suggested-undirected", "er-undirected") else "→"
            rows.append(
                '<div class="bs-row">'
                f'<span class="mono bs-title">{_esc(relation.get("source"))}</span>'
                f'<span class="bs-t">{arrow}</span>'
                f'<span class="mono bs-title">{_esc(relation.get("target"))}</span>'
                f'<span class="bs-t">欄位：{mappings}</span>'
                f'<span class="badge zone-{("gating" if relation.get("kind") == "declared" else "advisory")}">'
                f'{_esc(kind)}</span></div>')
        body = "".join(rows)
    return ('<div class="bsum"><div class="bs-head">Lineage 關聯'
            f'<span class="bs-hint">{note}</span></div>{body}</div>')


def _blocking_summary_html(findings: list[Finding]) -> str:
    """卡控摘要卡片：本次被哪些規則卡下來（點規則可篩選明細）。"""
    bs = blocking_summary(findings)
    if not bs["blocked"] and not bs["warned"]:
        return ""
    rows = []
    for b in bs["blocked"]:
        rows.append(
            f'<div class="bs-row"><span class="bs-dot bs-fail"></span>'
            f'<a href="#" onclick="filterRule(\'{_esc(b["rule"])}\');return false" '
            f'class="mono bs-rule">{_esc(b["rule"])}</a>'
            f'<span class="bs-title">{_esc(b["title"])}</span>'
            f'<span class="bs-t">擋下：{_esc("、".join(b["targets"]))}</span></div>')
    for b in bs["warned"]:
        rows.append(
            f'<div class="bs-row"><span class="bs-dot bs-warn"></span>'
            f'<a href="#" onclick="filterRule(\'{_esc(b["rule"])}\');return false" '
            f'class="mono bs-rule">{_esc(b["rule"])}</a>'
            f'<span class="bs-title">{_esc(b["title"])}</span>'
            f'<span class="bs-t">警告：{_esc("、".join(b["targets"]))}</span></div>')
    return ('<div class="bsum"><div class="bs-head">本次卡控摘要 — 被哪些規則卡下來'
            '<span class="bs-hint">（點規則代號可篩選明細）</span></div>'
            + "".join(rows) + "</div>")


def _checking_rule_summary_html(findings: list[Finding], meta: dict) -> str:
    crs = checking_rule_summary(findings, meta.get("checking_rule_ids_loaded"))
    rows = []
    for key, label, css in (
            ("failed", "擋下", "bs-fail"),
            ("warnings", "警告", "bs-warn"),
            ("passed", "通過", "bs-pass"),
            ("not_checked", "未實檢／略過", "bs-info"),
            ("advisory", "顧問", "bs-advisory")):
        ids = crs[key]
        if not ids:
            continue
        links = "、".join(
            f'<a href="#" onclick="filterRule(\'{_esc(rule_id)}\');return false" '
            f'class="mono bs-rule">{_esc(rule_id)}</a>' for rule_id in ids)
        rows.append(f'<div class="bs-row"><span class="bs-dot {css}"></span>'
                    f'<span class="bs-title">{label}</span><span class="bs-t">{links}</span></div>')
    return ('<div class="bsum"><div class="bs-head">Checking rule ID 摘要'
            '<span class="bs-hint">（點 rule ID 可篩選明細）</span></div>'
            + "".join(rows) + "</div>")


def _advisory_state_html(meta: dict, findings: list[Finding]) -> str:
    """Describe whether the advisory zone has real suggestions or is pending."""
    pending = [f for f in findings
               if f.zone == ZONE_ADVISORY and f.status == "skipped" and
               (f.source == "llm" or "skipped" in f.message.lower())]
    if meta.get("advisory_merged"):
        return "LLM／語意建議 · 一律提示 · <b>永不影響判定</b> · ✅ 已由 agent 補完"
    if pending:
        return ("LLM／語意建議 · 一律提示 · <b>永不影響判定</b> · "
                "本次未接 LLM，語意規則待補完")
    return "LLM／語意建議 · 一律提示 · <b>永不影響判定</b> · 不保證可重複"


def to_html(findings: list[Finding], meta: dict | None = None) -> str:
    s = summarize(findings)
    meta = meta or {}
    verdict_ok = s["compliant"]
    verdict_txt = "合規" if verdict_ok else "不合規"
    gen = _generated_at()
    domains = "、".join(meta.get("domains_loaded", [])) or "—"

    # build rows grouped by category
    cats_html = []
    for cat, title in CATEGORY_TITLES.items():
        cat_f = [f for f in findings if f.category == cat]
        if not cat_f:
            continue
        cat_f.sort(key=lambda f: (f.status != "fail", f.status != "warning",
                                  f.status != "skipped", f.status != "info"))
        n_fail = sum(1 for f in cat_f if f.status == "fail")
        n_warn = sum(1 for f in cat_f if f.status == "warning")
        rows = []
        for f in cat_f:
            zone = "閘門" if f.zone == ZONE_GATING else "顧問"
            rationale = (f'<div class="rationale">理由：{_esc(f.rationale)}</div>'
                         if f.rationale else "")
            ea = ""
            if f.expected or f.actual:
                ea += (f'<div class="ea"><span class="ea-l">期望</span>{_esc(f.expected)}'
                       f'<span class="ea-l">實際</span><span class="ea-bad">{_esc(f.actual)}</span></div>')
            if f.fix:
                ea += f'<div class="ea"><span class="ea-l">修法</span>{_esc(f.fix)}</div>' 
            rows.append(
                f'<tr class="row" data-status="{f.status}" data-zone="{f.zone}" '
                f'data-source="{_esc(f.source)}" '
                f'data-text="{_esc((f.check_id + " " + f.target + " " + f.message + " " + (f.rationale or "")).lower())}">'
                f'<td class="st st-{f.status}"><span class="dot"></span>{_ICON.get(f.status,"")}</td>'
                f'<td><span class="badge zone-{f.zone}">{zone}</span></td>'
                f'<td class="mono">{_esc(f.check_id)}</td>'
                f'<td class="mono">{_esc(f.target)}</td>'
                f'<td>{_esc(f.message)}{ea}{rationale}</td>'
                f'<td class="src">{_esc(f.source)}</td></tr>')
        cats_html.append(f"""
        <section class="cat" data-cat="{cat}">
          <button class="cat-head" onclick="toggleCat(this)">
            <span class="chev">▾</span>
            <span class="cat-title">{_esc(title)}</span>
            <span class="cat-meta">{len(cat_f)} 項{f' · {n_fail} 失敗' if n_fail else ''}{f' · {n_warn} 警告' if n_warn else ''}</span>
          </button>
          <div class="cat-body">
            <table>
              <thead><tr><th>狀態</th><th>區</th><th>檢查</th><th>對象</th><th>說明</th><th>來源</th></tr></thead>
              <tbody>{''.join(rows)}</tbody>
            </table>
          </div>
        </section>""")

    verdict_class = "ok" if verdict_ok else "bad"
    return f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>資料設計驗證報告</title>
<style>
  :root {{
    --bg:#f6f7f9; --card:#fff; --ink:#1d2127; --muted:#6b7280; --line:#e5e7eb;
    --ok:#15803d; --ok-bg:#dcfce7; --bad:#b91c1c; --bad-bg:#fee2e2;
    --warn:#b45309; --warn-bg:#fef3c7; --info:#1d4ed8; --info-bg:#dbeafe;
    --gating:#374151; --advisory:#7c3aed;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#0f1115; --card:#171a21; --ink:#e6e8ec; --muted:#9aa0aa; --line:#2a2f3a; }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,"Segoe UI","Microsoft JhengHei",sans-serif; line-height:1.6; }}
  .wrap {{ max-width:1080px; margin:0 auto; padding:24px 18px 64px; }}
  h1 {{ font-size:22px; font-weight:600; margin:0 0 4px; }}
  .sub {{ color:var(--muted); font-size:13px; margin-bottom:18px; }}
  .verdict {{ display:inline-flex; align-items:center; gap:8px; font-size:18px;
    font-weight:600; padding:8px 16px; border-radius:10px; }}
  .verdict.ok {{ color:var(--ok); background:var(--ok-bg); }}
  .verdict.bad {{ color:var(--bad); background:var(--bad-bg); }}
  .cards {{ display:flex; flex-wrap:wrap; gap:10px; margin:16px 0 8px; }}
  .kpi {{ flex:1; min-width:96px; background:var(--card); border:1px solid var(--line);
    border-radius:10px; padding:10px 14px; }}
  .kpi .n {{ font-size:20px; font-weight:600; }}
  .kpi .l {{ font-size:12px; color:var(--muted); }}
  .meta {{ background:var(--card); border:1px solid var(--line); border-radius:10px;
    padding:10px 14px; font-size:13px; color:var(--muted); margin:8px 0 18px; }}
  .controls {{ position:sticky; top:0; background:var(--bg); padding:10px 0;
    display:flex; flex-wrap:wrap; gap:8px; align-items:center; z-index:5; border-bottom:1px solid var(--line); }}
  .controls input[type=search] {{ flex:1; min-width:180px; padding:8px 12px;
    border:1px solid var(--line); border-radius:8px; background:var(--card); color:var(--ink); font-size:14px; }}
  .chip {{ padding:6px 12px; border:1px solid var(--line); border-radius:999px;
    background:var(--card); color:var(--ink); font-size:13px; cursor:pointer; user-select:none; }}
  .chip.active {{ background:var(--ink); color:var(--bg); border-color:var(--ink); }}
  .cat {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
    margin:14px 0; overflow:hidden; }}
  .cat-head {{ width:100%; text-align:left; background:none; border:none; color:var(--ink);
    padding:14px 16px; font-size:15px; cursor:pointer; display:flex; align-items:center; gap:10px; }}
  .cat-title {{ font-weight:600; }}
  .cat-meta {{ color:var(--muted); font-size:13px; margin-left:auto; }}
  .chev {{ transition:transform .15s; font-size:12px; color:var(--muted); }}
  .cat.collapsed .chev {{ transform:rotate(-90deg); }}
  .cat.collapsed .cat-body {{ display:none; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; }}
  th, td {{ text-align:left; padding:9px 12px; border-top:1px solid var(--line); vertical-align:top; }}
  th {{ color:var(--muted); font-weight:500; font-size:12px; }}
  .mono {{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:12.5px; }}
  .src {{ color:var(--muted); }}
  .rationale {{ color:var(--muted); font-size:12.5px; margin-top:3px; }}
  .badge {{ font-size:12px; padding:2px 8px; border-radius:999px; white-space:nowrap; }}
  .zone-gating {{ background:var(--info-bg); color:var(--info); }}
  .zone-advisory {{ background:#ede9fe; color:var(--advisory); }}
  .st {{ white-space:nowrap; }}
  .st .dot {{ display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:6px; vertical-align:middle; }}
  .st-fail .dot {{ background:var(--bad); }} .st-warning .dot {{ background:var(--warn); }}
  .st-pass .dot {{ background:var(--ok); }} .st-info .dot {{ background:var(--info); }}
  .st-skipped .dot {{ background:var(--muted); }}
  .empty {{ display:none; text-align:center; color:var(--muted); padding:30px; }}
  .hidden {{ display:none !important; }}
  .zones {{ display:flex; flex-wrap:wrap; gap:10px; margin:4px 0 12px; }}
  .zone-box {{ flex:1; min-width:280px; display:flex; align-items:center; gap:8px;
    background:var(--card); border:1px solid var(--line); border-radius:10px;
    padding:10px 14px; font-size:13px; color:var(--muted); }}
  .zone-box.zone-g {{ border-left:3px solid var(--info); }}
  .zone-box.zone-a {{ border-left:3px solid var(--advisory); }}
  .bsum {{ background:var(--card); border:1px solid var(--line); border-radius:12px;
    padding:12px 16px; margin:14px 0 4px; }}
  .bs-head {{ font-weight:600; font-size:14px; margin-bottom:8px; }}
  .bs-hint {{ color:var(--muted); font-weight:400; font-size:12px; margin-left:6px; }}
  .bs-row {{ display:flex; flex-wrap:wrap; align-items:baseline; gap:8px;
    padding:6px 0; border-top:1px solid var(--line); font-size:13.5px; }}
  .bs-dot {{ width:8px; height:8px; border-radius:50%; flex:none; align-self:center; }}
  .bs-fail {{ background:var(--bad); }} .bs-warn {{ background:var(--warn); }}
  .bs-pass {{ background:var(--ok); }} .bs-info {{ background:var(--info); }}
  .bs-advisory {{ background:var(--advisory); }}
  .bs-rule {{ color:var(--info); text-decoration:none; font-size:12.5px; }}
  .bs-rule:hover {{ text-decoration:underline; }}
  .bs-title {{ font-weight:600; }}
  .bs-t {{ color:var(--muted); font-size:12.5px; }}
  .ea {{ font-size:12.5px; margin-top:4px; display:flex; flex-wrap:wrap; gap:4px 8px; align-items:baseline; }}
  .ea-l {{ color:var(--muted); font-size:11.5px; border:1px solid var(--line); border-radius:4px; padding:0 5px; }}
  .ea-bad {{ color:var(--bad); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>資料設計驗證報告</h1>
  <div class="sub">產生時間 {gen}</div>
  <div class="verdict {verdict_class}">{'✅' if verdict_ok else '❌'} 判定：{verdict_txt}（會擋項目 {s['blocking_count']}）</div>

  {_checking_rule_summary_html(findings, meta)}
  {_blocking_summary_html(findings)}

  <div class="cards">
    <div class="kpi"><div class="n">{s['fail']}</div><div class="l">失敗</div></div>
    <div class="kpi"><div class="n">{s['warning']}</div><div class="l">警告</div></div>
    <div class="kpi"><div class="n">{s['pass']}</div><div class="l">通過</div></div>
    <div class="kpi"><div class="n">{s['info']}</div><div class="l">提示</div></div>
    <div class="kpi"><div class="n">{s['skipped']}</div><div class="l">略過</div></div>
    <div class="kpi"><div class="n">{s['gating']}</div><div class="l">閘門區</div></div>
    <div class="kpi"><div class="n">{s['advisory']}</div><div class="l">顧問區</div></div>
  </div>
  <div class="meta">方言 {_esc(meta.get('dialect','—'))} · 表數 {_esc(meta.get('tables','—'))}
    · 載入 skill {_esc(meta.get('skills_loaded',0))} 條 · domain：{_esc(domains)}
    <br><span style="color:var(--muted)">合規結果直接以 checking rule ID 呈現，不使用指紋或結果碼。</span></div>

  <div class="zones">
    <div class="zone-box zone-g">
      <span class="badge zone-gating">閘門區</span>
      <span>確定性檢查 · <b>決定合規判定</b> · 結果以 checking rule ID 呈現</span>
    </div>
    <div class="zone-box zone-a">
      <span class="badge zone-advisory">顧問區</span>
      <span>{_advisory_state_html(meta, findings)}</span>
    </div>
  </div>

  {_lineage_html(meta)}

  <div class="controls">
    <input type="search" id="q" placeholder="搜尋檢查、對象、說明…" oninput="applyFilters()">
    <span class="chip active" data-f="status" data-v="all" onclick="pick(this)">全部</span>
    <span class="chip" data-f="status" data-v="fail" onclick="pick(this)">只看失敗</span>
    <span class="chip" data-f="status" data-v="warning" onclick="pick(this)">只看警告</span>
    <span class="chip" data-f="zone" data-v="gating" onclick="pick(this)">只看閘門區</span>
    <span class="chip" data-f="zone" data-v="advisory" onclick="pick(this)">只看顧問區</span>
  </div>

  {''.join(cats_html)}
  <div class="empty" id="empty">沒有符合篩選條件的項目。</div>
</div>
<script>
  var F = {{ status:"all", zone:"all" }};
  function pick(el) {{
    var f = el.dataset.f, v = el.dataset.v;
    // toggle: clicking active zone resets to all
    if (f === "status") {{
      document.querySelectorAll('.chip[data-f=status]').forEach(c=>c.classList.remove('active'));
      el.classList.add('active'); F.status = v;
    }} else {{
      var was = el.classList.contains('active');
      document.querySelectorAll('.chip[data-f=zone]').forEach(c=>c.classList.remove('active'));
      if (was) {{ F.zone = "all"; }} else {{ el.classList.add('active'); F.zone = v; }}
    }}
    applyFilters();
  }}
  function applyFilters() {{
    var q = document.getElementById('q').value.trim().toLowerCase();
    var shown = 0;
    document.querySelectorAll('section.cat').forEach(function(sec) {{
      var vis = 0;
      sec.querySelectorAll('tr.row').forEach(function(r) {{
        var ok = true;
        if (F.status !== "all" && r.dataset.status !== F.status) ok = false;
        if (F.zone !== "all" && r.dataset.zone !== F.zone) ok = false;
        if (q && r.dataset.text.indexOf(q) === -1) ok = false;
        r.classList.toggle('hidden', !ok);
        if (ok) vis++;
      }});
      sec.classList.toggle('hidden', vis === 0);
      shown += vis;
    }});
    document.getElementById('empty').style.display = shown === 0 ? 'block' : 'none';
  }}
  function toggleCat(btn) {{ btn.parentElement.classList.toggle('collapsed'); }}
  function filterRule(rule) {{
    var q = document.getElementById('q');
    q.value = rule.toLowerCase();
    applyFilters();
    q.scrollIntoView({{behavior:'smooth', block:'start'}});
  }}
</script>
</body>
</html>"""
