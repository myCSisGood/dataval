#!/usr/bin/env python3
"""本機小型 web app：在瀏覽器完成「填四件 → 送驗 → 看報告 → 套用修正 → 重驗」。

    .venv/bin/python webapp.py            # 預設 http://localhost:8765

純標準庫（http.server），不加框架依賴，呼應 pyproject 目前只有 sqlglot/PyYAML
的零依賴風格。與 CLI 完全獨立：webapp 是否啟動不影響 run.py／promote.py／rules.py
能否使用；送驗走的是**同一個** dataval.engine.validate()（不 shell 出去跑 run.py），
兩條路徑共用同一個驗證函式，避免邏輯分叉。

路由：
  GET  /                   擴充後的 frontend/index.html
  GET  /api/subjects       列出 input/ 下 subject 與四件齊全狀態
  GET  /api/subject?name=X 回傳既有 subject 的四件內容（供載入編輯框）
  GET  /api/lineage-graph  正式區全域關聯圖（prodgraph.export_graph）
  POST /api/validate       寫入 input/<name>/ 後 in-process 驗證，回傳 report JSON
"""
from __future__ import annotations
import json
import os
import re
import shutil
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from dataval.engine import load_config, validate
from dataval.report import to_json
from dataval.llm import NullLLM
from dataval.prodgraph import export_graph
from dataval import precheck as preflight

import run as R  # 沿用 INPUT_DIR/CONFIG/DOMAIN_ROOT… 與 load_input_v2

HERE = R.HERE
FRONTEND = os.path.join(HERE, "frontend", "index.html")
NAME_RE = re.compile(r"[A-Za-z0-9_-]+")
PORT = int(os.environ.get("DATAVAL_WEBAPP_PORT", "8765"))

_CFG = None


def _cfg():
    global _CFG
    if _CFG is None:
        _CFG = load_config(R.CONFIG)
    return _CFG


# ------------------------------------------------------------ 資料存取

def list_subjects() -> list[dict]:
    out = []
    for ddl_path in R.find_ddls():
        name = os.path.splitext(os.path.basename(ddl_path))[0]
        pieces = preflight.locate_pieces(ddl_path)
        present = {
            "sql": os.path.isfile(ddl_path),
            "samples": os.path.isdir(pieces["samples"]),
            "relations": os.path.isfile(pieces["relations"]),
            "context": os.path.isfile(pieces["context"]),
        }
        pre = preflight.run_precheck(ddl_path)
        out.append({"name": name, "passed": pre.passed, "pieces": present})
    return out


def read_subject(name: str) -> dict | None:
    """讀既有 subject 的四件內容，供前端載入編輯框。"""
    for ddl_path in (os.path.join(R.INPUT_DIR, name, name + ".sql"),
                     os.path.join(R.INPUT_DIR, name + ".sql")):
        if os.path.isfile(ddl_path):
            break
    else:
        return None
    pieces = preflight.locate_pieces(ddl_path)
    samples: dict[str, str] = {}
    sdir = pieces["samples"]
    if os.path.isdir(sdir):
        for fn in sorted(os.listdir(sdir)):
            if fn.lower().endswith(".csv"):
                with open(os.path.join(sdir, fn), encoding="utf-8") as f:
                    samples[os.path.splitext(fn)[0]] = f.read()

    def _read(path: str) -> str:
        return (open(path, encoding="utf-8").read()
                if os.path.isfile(path) else "")

    return {
        "name": name,
        "ddl": _read(ddl_path),
        "samples": samples,
        "relations": _read(pieces["relations"]),
        "context": _read(pieces["context"]),
    }


def validate_payload(payload: dict) -> tuple[int, dict]:
    """把前端送來的四件寫進 input/<name>/，再跑同一個驗證函式。"""
    name = str(payload.get("name", "")).strip()
    if not NAME_RE.fullmatch(name):
        return 400, {"error": "名稱只能包含英數、底線或連字號"}
    ddl = str(payload.get("ddl", ""))
    samples = payload.get("samples", {}) or {}
    relations = str(payload.get("relations", "") or "")
    context = str(payload.get("context", "") or "")
    if not isinstance(samples, dict):
        return 400, {"error": "samples 必須是 {表名: CSV文字} 對照"}
    for table in samples:
        if not NAME_RE.fullmatch(str(table)):
            return 400, {"error": f"表名不合法：{table}"}

    dest = os.path.join(R.INPUT_DIR, name)
    os.makedirs(dest, exist_ok=True)
    sdir = os.path.join(dest, "samples")
    shutil.rmtree(sdir, ignore_errors=True)
    os.makedirs(sdir)
    with open(os.path.join(dest, f"{name}.sql"), "w", encoding="utf-8") as f:
        f.write(ddl)
    for table, csv_text in samples.items():
        with open(os.path.join(sdir, f"{table}.csv"), "w", encoding="utf-8") as f:
            f.write(str(csv_text))
    with open(os.path.join(dest, "relations.yaml"), "w", encoding="utf-8") as f:
        f.write(relations)
    with open(os.path.join(dest, "context.md"), "w", encoding="utf-8") as f:
        f.write(context)

    # 走與 run.py 相同的前置檢核 → 驗證路徑（四件不齊就誠實回缺件明細，不產報告）。
    ddl_path = os.path.join(dest, f"{name}.sql")
    pre = preflight.run_precheck(ddl_path)
    if not pre.passed:
        failed = [{"label": it.label, "detail": it.detail}
                  for it in pre.items if not it.ok]
        return 200, {"precheck_failed": True, "name": name,
                     "failed": failed,
                     "console": preflight.console_lines(pre),
                     "markdown": preflight.to_markdown(pre)}
    case = R.load_input_v2(ddl_path, pre)
    schema, findings, meta = validate(
        case.ddl, _cfg(), sample_data=case.sample, context=case.context,
        business_keys=case.business_keys, lineage_spec=case.lineage,
        relations=case.relations, er_diagram=case.er_diagram,
        diagnostics=case.diagnostics, llm=NullLLM(),
        domain_root=R.DOMAIN_ROOT, rules_root=R.RULES_ROOT, domains=case.domains,
        config_dir=R.CONFIG_DIR, production_root=R.PRODUCTION_ROOT)
    meta["case_config"] = case.config_source
    return 200, json.loads(to_json(findings, meta))


# ------------------------------------------------------------ HTTP handler

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # 安靜些，只印錯誤
        pass

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        route = urlparse(self.path)
        path = route.path
        if path == "/" or path == "/index.html":
            if not os.path.isfile(FRONTEND):
                return self._json(500, {"error": "找不到 frontend/index.html"})
            with open(FRONTEND, "rb") as f:
                return self._send(200, f.read(), "text/html; charset=utf-8")
        if path == "/api/subjects":
            return self._json(200, {"subjects": list_subjects()})
        if path == "/api/subject":
            name = (parse_qs(route.query).get("name") or [""])[0]
            data = read_subject(name) if NAME_RE.fullmatch(name or "") else None
            if data is None:
                return self._json(404, {"error": "找不到 subject"})
            return self._json(200, data)
        if path == "/api/lineage-graph":
            return self._json(200, export_graph(R.PRODUCTION_ROOT))
        return self._json(404, {"error": "no such route"})

    def do_POST(self):
        route = urlparse(self.path)
        if route.path != "/api/validate":
            return self._json(404, {"error": "no such route"})
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        try:
            payload = json.loads(raw or b"{}")
        except Exception as e:
            return self._json(400, {"error": f"JSON 解析失敗：{e}"})
        try:
            code, obj = validate_payload(payload)
        except Exception as e:  # 別讓單次請求打掛整個 server
            import traceback
            traceback.print_exc()
            return self._json(500, {"error": f"{type(e).__name__}: {e}"})
        return self._json(code, obj)


def main():
    server = ThreadingHTTPServer(("localhost", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"dataval webapp 已啟動：{url}")
    print("  · 送驗會寫入 input/<名>/ 並跑與 CLI 相同的驗證函式。")
    print("  · CLI（run.py／promote.py／rules.py）不受影響，可獨立使用。")
    print("  · Ctrl-C 結束。")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        server.shutdown()


if __name__ == "__main__":
    main()
