# 改善待辦（backlog）

這份檔案誠實記錄「探勘／實作過程中發現、但當下判斷不該做或優先度較低」的項目，
避免它們散落在記憶裡。做了的請移除；新發現的請往下追加。

## 技術債

- **4 支入口腳本各自重複宣告路徑常數。**
  `run.py`／`rules.py`／`promote.py`／`production_audit.py`（以及新增的
  `simulate_impact.py`／`webapp.py`）各自宣告 `HERE`／`DOMAIN_ROOT`／`RULES_ROOT`／
  `PRODUCTION_ROOT`／`CONFIG` 等。本輪的 `dataval/report_paths.py` 只解決了「報告輸出
  路徑分類」這一小塊；把所有入口共用的路徑常數收斂成一個 `dataval/paths.py`（或
  `dataval/settings.py`）仍待處理。做的時候要小心：`run.py` 的 `PRODUCTION_ROOT`
  沒吃環境變數，`promote.py`／`simulate_impact.py` 有吃 `DATAVAL_PRODUCTION_DIR`，
  收斂時要統一並保持相容。

- **`config/_engine/advisory_result.schema.json` 是第二份權威來源。**
  真正的驗證是 `dataval/advisory_export.py::validate_advisory_result()`（手寫、零依賴），
  schema 檔從未被程式讀取。本輪（第 0 項）已修正 prompt 內的路徑引用、把規則內嵌進
  prompt、並在函式上方標註三處耦合，但**沒有收斂**成單一來源。之後可二選一：
  (a) 讓程式真的去讀 schema 檔驗證（需引入 jsonschema 依賴，與零依賴取向衝突）；
  (b) 直接刪掉 schema 檔、只留手寫驗證＋prompt 內嵌說明。目前三處內容一致，但仍會漂移。

## 功能候選

- **DataHub 必填欄位檢驗。**（使用者更早提過，獨立於本輪所有項目。）
  對照 `config/_engine/default.yaml` 的 DataHub 設定，檢查每張表／欄位是否具備
  DataHub 上架所需的必填 metadata（owner、domain、description 等），缺的報 warning。

- **`scaffold_input.py` 的 FK 推測對 ClickHouse 幾乎是空轉。**
  sqlglot 解析 ClickHouse DDL 時通常不會產出 `foreign_keys`（ClickHouse 不強制 FK），
  所以 `relations.yaml` 幾乎都落在 `relations: []`。可加一層啟發式：從跨表共用的
  `*_id` 欄位推測候選關聯（比照 lineage 的 business-key 建議邏輯），一樣標「務必確認」。

- **`frontend/` 全域關聯圖的自動佈局很陽春。**
  目前是「最長路徑分層＋同層垂直排開」的手工佈局，節點多時會重疊、交叉線多。若要更好，
  可能需要引入輕量佈局演算法（如 dagre）——這會**牴觸 frontend 現有的「零依賴」承諾**，
  值不值得放寬這個限制需要另外評估（可考慮把佈局演算法內嵌成單檔、仍不走 npm/CDN）。

## 測試補強

- 純函式已補 `tests/tooling_test.py`（`report_paths`、`report.diff_findings`、
  `prodgraph.export_graph`、advisory prompt 路徑）。**尚缺**：`scaffold_input.py`
  的樣本產生與 `context.md` 佔位、`simulate_impact.py` 的 regressed 判定，可再補。

- `webapp.py` 目前無自動化測試；可加一個以 `DATAVAL_INPUT_DIR` 指向暫存目錄、
  用 `http.client` 打 `POST /api/validate` 的整合測試（驗證與 CLI 同源、precheck 缺件
  會回 `precheck_failed`）。前端邏輯（layering／applyFix）已用 node 手動驗證，
  若要自動化需引入 headless browser——與零依賴取向需權衡。

## 行為取捨（已知、刻意）

- **`webapp.py` 的送驗會把四件寫進 `input/<名>/` 並保留。** 這是刻意的（送驗＝以
  瀏覽器編輯一份輸入並驗證），但意味著在 UI 打同名會覆蓋既有輸入。若要更安全，可分離
  「暫存草稿區」與「正式 input/」，或加覆蓋前確認。

- **`simulate_impact.py` 無法涵蓋依賴樣本的規則。** 正式區不存樣本（設計如此），所以
  型別對樣本、join key 編碼、relations 基數實檢等在模擬中不會重跑；工具已在終端明確
  揭露此限制。若要完整，需要在晉升記錄裡多存「樣本衍生的中間結論」而非樣本本身。
