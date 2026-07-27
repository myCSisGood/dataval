"""E2E 流程（domain flows）。

每個 domain 可在 config/<域>/flows/ 放 `*.flow.yaml`，描述資料
從來源到消費端的端到端流程。推薦格式（YAML）：

    flow: order_to_revenue            # 流程代號
    title: 訂單到營收                  # 顯示名稱
    description: 一句話說明
    stages:                           # 依序的站點
      - name: 結帳服務
        kind: source                  # source | table | report
      - name: orders
        kind: table                   # kind=table 時 name 必須是表名
      - name: 營收日報
        kind: report

引擎行為（確定性、只出資訊與診斷，不擋）：
  FLOW.CONTEXT（info／顧問區）  本次 DDL 的表出現在某流程時，標註它的
      位置與上下游站點——讓設計者與審查者知道這張表在端到端流程的角色。
  FLOW.SPEC（warning／閘門區）  flow 檔無法解析或缺必要欄位時提醒，
      不靜默吞掉。
"""
from __future__ import annotations

import os

import yaml

from .model import Finding, Schema, ZONE_ADVISORY, ZONE_GATING

VALID_KINDS = ("source", "table", "report")


def _domain_folders(config_dir: str, domains: list[str] | None) -> list[str]:
    root = config_dir
    if os.path.isdir(os.path.join(config_dir, "domains")):
        root = os.path.join(config_dir, "domains")  # 舊佈局相容
    if not os.path.isdir(root):
        return []
    folders = {f.lower(): f for f in os.listdir(root)
               if os.path.isdir(os.path.join(root, f))
               and not f.startswith("_")}
    out, seen = [], set()
    for want in ["Common"] + [d for d in (domains or []) if d]:
        folder = folders.get(want.strip().lower())
        if folder and folder not in seen:
            seen.add(folder)
            out.append(os.path.join(root, folder))
    return out


def load_flows(config_dir: str, domains: list[str] | None
               ) -> tuple[list[dict], list[Finding]]:
    """載入流程定義。回傳 (flows, 診斷 findings)。"""
    flows: list[dict] = []
    problems: list[Finding] = []
    for dom_path in _domain_folders(config_dir, domains):
        flows_dir = os.path.join(dom_path, "flows")
        if not os.path.isdir(flows_dir):
            continue
        domain = os.path.basename(dom_path)
        for fn in sorted(os.listdir(flows_dir)):
            if not fn.endswith((".flow.yaml", ".flow.yml")):
                continue
            path = os.path.join(flows_dir, fn)
            label = f"{domain}/flows/{fn}"
            try:
                with open(path, encoding="utf-8") as f:
                    spec = yaml.safe_load(f) or {}
                if not isinstance(spec, dict):
                    raise ValueError("根節點必須是 mapping")
                stages = spec.get("stages")
                if not isinstance(stages, list) or not stages:
                    raise ValueError("缺 stages 清單")
                for i, stage in enumerate(stages, start=1):
                    if not isinstance(stage, dict) or not stage.get("name"):
                        raise ValueError(f"第 {i} 站缺 name")
                    kind = stage.get("kind", "table")
                    if kind not in VALID_KINDS:
                        raise ValueError(
                            f"第 {i} 站 kind '{kind}' 不合法"
                            f"（限 {'/'.join(VALID_KINDS)}）")
            except Exception as e:
                problems.append(Finding(
                    "FLOW.SPEC", "structural", "warning", label,
                    f"E2E 流程檔無法使用：{type(e).__name__}: {e}",
                    severity="warning", source="rule", zone=ZONE_GATING,
                    fix="依 flows 資料夾內範例的 YAML 格式修正。"))
                continue
            spec["_domain"], spec["_source"] = domain, label
            flows.append(spec)
    return flows, problems


def run(schema: Schema, domains: list[str] | None,
        config_dir: str) -> list[Finding]:
    flows, findings = load_flows(config_dir, domains)
    if not flows:
        return findings
    table_names = {t.name.lower(): t.name for t in schema.tables}
    for spec in flows:
        stages = spec["stages"]
        for idx, stage in enumerate(stages):
            if stage.get("kind", "table") != "table":
                continue
            hit = table_names.get(str(stage["name"]).lower())
            if not hit:
                continue
            prev_stage = stages[idx - 1]["name"] if idx > 0 else "（起點）"
            next_stage = (stages[idx + 1]["name"]
                          if idx + 1 < len(stages) else "（終點）")
            title = spec.get("title") or spec.get("flow") or spec["_source"]
            findings.append(Finding(
                "FLOW.CONTEXT", "structural", "info", hit,
                f"此表位於 E2E 流程「{title}」第 {idx + 1}/{len(stages)} 站；"
                f"上游站點：{prev_stage}；下游站點：{next_stage}。"
                "設計變更時請沿流程確認上下游影響。",
                severity="info", source="rule", zone=ZONE_ADVISORY))
    return findings
