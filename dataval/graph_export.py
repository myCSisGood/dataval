"""把正式區跨 subject 的關聯圖匯出成可序列化資料（供前端／工具視覺化）。

刻意獨立成一個檔案，不寫進 prodgraph.py——prodgraph.py 是被 provenance 逐檔雜湊的
validator 來源，動它會讓驗證 bundle 版本碼改變。這裡只重用 prodgraph 的既有掃描
（load_subjects）與邊計算（_edges），不重寫邏輯，也不影響閘門。
"""
from __future__ import annotations

from .prodgraph import load_subjects, _edges


def export_graph(production_root: str,
                 domains: list[str] | None = None) -> dict:
    """匯出正式區跨 subject 的全域關聯圖。

    回傳 {"nodes": [{"id","domain","subject","table"}], "edges": [{"from","to"}]}。
    node id 與 _edges/_endpoint_key 一致：domain 限定的 "<domain>.<table>"。
    可用 domains 過濾只匯出指定 domain 的 subject。
    """
    wanted = {d.strip().lower() for d in domains} if domains else None
    nodes: dict[str, dict] = {}
    edges: list[dict] = []
    seen_edge: set[tuple[str, str]] = set()
    for s in load_subjects(production_root):
        if wanted is not None and s.domain.lower() not in wanted:
            continue
        for tname in s.tables:
            nid = f"{s.domain.lower()}.{tname.lower()}"
            nodes.setdefault(nid, {"id": nid, "domain": s.domain,
                                   "subject": s.name, "table": tname})
        for up, down in _edges(s.relations, s.domain):
            # 端點可能指向他 subject 的表；補成節點（domain 取自 key 前綴）。
            for nid in (up, down):
                if nid not in nodes:
                    dom, _, tbl = nid.partition(".")
                    nodes[nid] = {"id": nid, "domain": dom, "subject": "",
                                  "table": tbl or nid}
            key = (up, down)
            if key not in seen_edge:
                seen_edge.add(key)
                edges.append({"from": up, "to": down})
    return {"nodes": sorted(nodes.values(), key=lambda n: n["id"]),
            "edges": sorted(edges, key=lambda e: (e["from"], e["to"]))}
