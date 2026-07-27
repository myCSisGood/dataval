# dataval 報告檢視器（frontend）

單檔、零依賴、零建置的報告 viewer。它**不重畫報告內容**，而是在執行期讀取
`run.py` 產出的 `reports/<名>.report.json`，分閘門區／顧問區呈現。與 `run.py` 直接
產出的 `*.report.html` 的差別：那份把資料**烤進**單一 HTML；這份是**解耦的元件**，
在執行期吃 JSON，所以別的專案可以餵自己的報告資料進來，不必重寫渲染。

viewer 有七個分頁（多數需後端，見下方 webapp；純 `file://` 開啟時會提示先啟動 webapp）：

- **報告**：有後端時直接列出可檢視的報告，點一下即檢視（不必拖拉）；離線時退回拖拉載入。
- **送驗**：四個檔案上傳區（DDL／樣本 CSV 多選／relations.yaml／context.md）＋一行主題名稱；
  上傳會填入可編輯的欄位，四件皆非空才可送出。名稱重複會提示會覆蓋。
- **存放區**：把 reports／rules_history／drafts 依資料夾**分層**列出，點檔案即檢視
  （html 內嵌 iframe、其餘純文字）；report.json 可一鍵在「報告」分頁開啟。
- **Report diff**：先選**系列（subject）**，再選同系列的兩個版本比對——改規則後重新送驗會
  累積歷史版本（存於 `reports/.history/`），才有多版本可比。
- **影響模擬**：重跑正式區看規則變更會讓哪些 subject 由合規變不合規。
- **Rule story**：規則版本歷程；點「看這版全部規則」進到該版完整規則清單（依 domain 分組）。
- **Lineage**：可選要看哪一份報告的單一 subject 關聯圖；另畫全域正式區關聯圖。

## 立即使用

- **雙擊 `index.html`**（`file://` 即可）→ 「報告」分頁把 `reports/xxx.report.json`
  拖進去，或按「選擇 JSON 檔」。「Lineage」分頁會畫出這份報告的關聯圖。
- **用網址參數**（需 http 伺服器）：
  ```bash
  .venv/bin/python -m http.server 8000     # 在專案根目錄
  # 開 http://localhost:8000/frontend/index.html?src=/reports/order.report.json
  ```

## 本機 web app（webapp.py）— 送驗與全域關聯圖

「送驗」分頁與 Lineage 的「全域正式區關聯圖」需要一個本機後端。純標準庫、零框架：

```bash
.venv/bin/python webapp.py        # 預設 http://localhost:8765
```

它 in-process 呼叫**與 CLI 相同的** `dataval.engine.validate()`（不 shell 出去跑
`run.py`）。CLI（`run.py`／`promote.py`／`rules.py`）完全不受影響、可獨立使用。

| 路由 | 用途 |
|---|---|
| `GET /` | 這個 `index.html` |
| `GET /api/subjects` | 列出 `input/` 下 subject 與四件齊全狀態（送驗分頁的重名偵測也用它） |
| `GET /api/subject?name=X` | 既有 subject 的四件內容（供「載入既有」填入編輯框） |
| `GET /api/lineage-graph` | 正式區全域關聯圖（`graph_export.export_graph`） |
| `GET /api/outputs` | 列出 reports／rules_history／drafts 的輸出檔（存放區） |
| `GET /api/file?path=X` | 檢視單一輸出檔（路徑限 reports 等允許根，防穿越） |
| `GET /api/rule-history` | 規則版本歷程（`rules_history/*.json` 快照，供 Rule story） |
| `GET /api/report-diff?old=&new=` | 比對兩份報告（`report.diff_findings`） |
| `GET /api/report-series` | 報告依系列（subject）分組，含目前版與 `.history/` 歷史版 |
| `GET /api/rule-snapshot?file=` | 某個 `rules_history` 快照的完整規則清單（rule story 點進去） |
| `GET /api/simulate-impact` | 正式區規則影響模擬（`simulate_impact.simulate_all`） |
| `POST /api/validate` | 把四件寫入 `input/<名>/`，驗證後把三式報告落地到 `reports/`（並存 `.history/` 時間戳版），回傳 report JSON |

送驗流程：填四件 → 「送出驗證」（四件皆非空才啟用）→ 看報告 → 對有修法的 finding 按
「套用修正到編輯框」（只把 `-- TODO(fix): …` 插進 DDL 編輯框，**不自動送出也不改檔**）
→ 自行確認後再按「送出驗證」重驗。沒有後端時（純 `file://` 雙擊），送驗分頁會提示需先
啟動 webapp，其餘分頁照常可用。

## 整合契約（接到另一個專案）

這個 viewer 只依賴**一件事**：`run.py` 產出的報告 JSON schema。任何專案只要能拿到
同一份 JSON，就能用它顯示。三種載入方式，擇一：

| 方式 | 呼叫 | 適用 |
|---|---|---|
| 網址參數 | `index.html?src=<報告 json 的 URL>` | 你的專案把報告放在可被 fetch 的路徑 |
| JS API | `window.dataval.render(reportObj)` 或 `window.dataval.loadUrl(url)` | 你的頁面自己拿到 JSON 後餵進來 |
| iframe 嵌入 | 父頁 `iframe.contentWindow.postMessage({type:'dataval-report', report:{…}}, '*')` | 把 viewer 當黑箱嵌進既有前端 |

### JSON schema（viewer 讀的欄位）

`run.py` → `reports/<名>.report.json` 的頂層結構（`dataval/report.py` 的
`to_json`）：

```jsonc
{
  "summary":  { "compliant": bool, "total", "fail", "warning", "pass",
                "advisory", "skipped", "blocking_count", "gating" },
  "meta":     { "domains_loaded": [..], "case_config": "…",
                "subject"?: "…", "checking_rule_ids_loaded": [..] },
  "findings": [ { "check_id","category","status","target","message",
                  "zone","source","expected","actual","fix","rationale" } ],
  "blocking_summary": { "blocked": [ { "rule","reason","targets":[..] } ] },
  "generated_at": "…"
}
```

- `status` ∈ `fail｜warning｜pass｜info｜skipped`；`zone` ∈ `gating｜advisory`。
- **合規判定只看 `summary.compliant`（由閘門區決定）**；顧問區一律 info，viewer 不
  拿它改變判定，只呈現。
- viewer 對缺欄位是寬容的（少 `blocking_summary`、`meta.subject` 都不會壞），
  但 `summary` 必須存在，否則會顯示「這不是 dataval 報告 JSON」。

### 產生要餵的資料

```bash
.venv/bin/python run.py            # 產出 reports/<名>.report.json（＋.md/.html）
```

另一個專案若要即時驗證，直接呼叫引擎、把 `to_json` 的輸出交給 viewer 即可：

```python
from dataval.engine import load_config, validate
from dataval.report import to_json
# validate(...) 回傳 findings, meta → to_json(findings, meta) 就是 viewer 吃的字串
```

## 為什麼零依賴

專案本身標榜「本地、可重現」。viewer 沿用這個調性：沒有 npm、沒有 CDN、沒有建置
步驟，`file://` 雙擊即開。要嵌進 React/Vue 專案時，把 `index.html` 當靜態資產放進
去、用上面三種方式之一餵資料即可；若要原生元件化，schema 一節就是你重畫時要對齊的
唯一契約。
