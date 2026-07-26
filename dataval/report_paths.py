"""報告輸出路徑分類。

reports/ 過去是扁平的（reports/<名>.report.json）。案例變多後，同一資料夾塞滿
不同 domain 的報告不好翻。這裡把報告依「代表性 domain」分到子資料夾
（reports/<域>/<名>.report.*），並提供一個不需要知道 domain 就能回頭定位既有
報告的搜尋函式，讓 merge_advisory.py／promote.py 這類「只有名字、沒有 domain」的
呼叫端仍找得到報告。向下相容：舊的扁平報告仍會被找到。

precheck.md 刻意**不**分類——前置檢核可能在完全不知道 domain 的情況下就失敗
（例如 context.md 整份不存在），沒有穩定的分類依據，維持扁平放在 reports/ 根。
"""
from __future__ import annotations
import os

UNCATEGORIZED = "_uncategorized"


def primary_domain(domains_loaded: list[str] | None) -> str:
    """挑一個代表性 domain 當分類資料夾。

    優先第一個非 Common 的 domain（案例的實質歸屬）；全部都是 Common 就回
    "Common"；完全沒有 domain 資訊（空清單／None）回 "_uncategorized"。
    """
    domains = [d for d in (domains_loaded or []) if d and str(d).strip()]
    if not domains:
        return UNCATEGORIZED
    for d in domains:
        if str(d).strip() != "Common":
            return str(d).strip()
    return "Common"


def report_dir_for(base: str, domains_loaded: list[str] | None) -> str:
    """base/<primary_domain>/，並確保資料夾存在後回傳其路徑。"""
    target = os.path.join(base, primary_domain(domains_loaded))
    os.makedirs(target, exist_ok=True)
    return target


def find_report_json(base: str, name: str) -> str | None:
    """在 base 底下尋找 <name>.report.json，供不知道 domain 的呼叫端定位既有報告。

    先找分類子資料夾（新佈局），再退回 base 根的扁平路徑（向下相容）。
    都找不到回 None。
    """
    fname = f"{name}.report.json"
    if os.path.isdir(base):
        for entry in sorted(os.listdir(base)):
            sub = os.path.join(base, entry)
            if os.path.isdir(sub):
                candidate = os.path.join(sub, fname)
                if os.path.isfile(candidate):
                    return candidate
    flat = os.path.join(base, fname)
    return flat if os.path.isfile(flat) else None
