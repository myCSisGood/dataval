# Agent 操作規範

這是 ClickHouse DDL 資料治理工具。完整使用方式見 `README.md`；新增規則時再讀
`SKILL_AUTHORING.md`。

## 驗證 DDL 並輸出報告（標準流程）

使用者說「檢查 input／跑檢查／產生報告／輸出報告」等，都是要一份**完整報告**。
一份完整報告 = 閘門區 ＋ **已補完的顧問區**。請完整跑完以下三步，缺一不可：

```bash
.venv/bin/python run.py            # ① 閘門區＋產出報告骨架與 advisory_prompt
# ② run.py 若在結尾印出「⚠️ 顧問區尚未補完」，你（agent）必須用自身 LLM，
#    對每個列出的主題讀 reports/<名>.advisory_prompt.md，依其格式與 schema
#    產出 reports/<名>.advisory_result.json（顧問建議一律 info、繁中、提問語氣）
.venv/bin/python merge_advisory.py           # ③ 把建議合回三式報告＋HTML
.venv/bin/python merge_advisory.py --status  # 驗收：exit 0 = 顧問區全數補完
```

**沒有做完 ②③ 就把報告交給使用者 = 交付不完整的報告**（HTML 顧問區只會顯示
「待補完」、report 顯示未接 LLM）。除非本機設了 `DATAVAL_LLM_BASE_URL`
讓 `run.py` 直接填顧問區（此時 run.py 不會印待補提示，跳過 ②③ 即可）。
詳細補完格式見下方「補完顧問區」。

新 DDL 使用一 subject 一資料夾：三件必備 `input/<名稱>/<名稱>.sql`、
`relations.yaml`、`context.md`，外加選填的 `samples/<表>.csv`（缺樣本仍會產報告，
只是樣本相關檢查略過）。`context.md` 的 front-matter
是 domains 與 business_keys 的權威來源；`relations.yaml` 是明確 lineage 宣告。
`config/<域>/cases/<名稱>.yaml` 只保留相容模式與內部 fixture 的補充資料。

Mermaid ER 參考模型放在 `config/<域>/erd/`；個案圖可放
`config/<域>/cases/<名稱>.mmd`。ER 關係只能轉成 lineage 顧問候選；沒有
`relations.yaml` 明確宣告時，不得把 ER association 說成已確認的資料流向。

`Common` 永遠載入；其他 domain 只由 `context.md` 的 `domains` 指定。不得把 ClickHouse
`ORDER BY` 或 `PRIMARY KEY` 當成 Business Key。外部 lineage 來源必須存在於已選
domain 的 `production/`；沒有 YAML 時只能把推測稱為建議，不能說成已確認血緣。

## 補完顧問區

這是「輸出報告」的必要環節，不是選配。`run.py` 是零 LLM 的閘門區行程，語意
建議（check-llm 規則、命名語意、主體性概念）需要 agent 用**自身 LLM** 補上。
`run.py` 結尾若印出待補主題清單，代表顧問區還沒填。Agent 應：

1. 對每個待補主題讀取 `reports/<名稱>.advisory_prompt.md`。
2. 依其中格式與 `config/_engine/advisory_result.schema.json`，用自身 LLM 產生
   `reports/<名稱>.advisory_result.json`（繁體中文、對設計者的提問語氣、不下結論）。
3. 執行 `.venv/bin/python merge_advisory.py`（會把建議合回 md／json／html）。
4. 執行 `.venv/bin/python merge_advisory.py --status` 驗收（exit 0 = 全數補完）；
   確認 `.report.html` 顧問區顯示真實建議，閘門結果不變。

**完整的 JSON 格式與驗證規則已內嵌在生成的 `advisory_prompt.md` 裡**（欄位、
非空字串、skill id 樣式等逐條列出），照它做即可，不必另外查
`config/_engine/advisory_result.schema.json` 或本檔——本檔只講流程，格式以 prompt 為準。

顧問建議一律是 `info`，永遠不能改變合規判定。合併程式會逐項比較合併前後的
gating findings，不一致就拒絕寫入。若本機設了 `DATAVAL_LLM_BASE_URL`，`run.py`
會在單次執行直接填顧問區，這時不需要上面的手動補完。

## 新增規則

```bash
.venv/bin/python rules.py new <rule_id>
.venv/bin/python rules.py check
.venv/bin/python run.py
```

指定 domain／區域時使用：

```bash
.venv/bin/python rules.py new <domain> <gating|advisory> <rule_id>
```

規則格式、允許的 checking verbs 與檢查清單以 `SKILL_AUTHORING.md` 為準。

### 由 LLM 起草規則（drafts/ 流程）

使用者以自然語言描述規則需求時，走起草流程而非直接寫進 knowhow：

```bash
.venv/bin/python rules.py draft <域> <gating|advisory> <rule_id> "<需求描述>"
```

未接本地 LLM 時會產出 `drafts/<rule_id>.prompt.md`；agent 依該檔的 system
指引產出 `drafts/<rule_id>.md`（只含規則內容本身）。**必須提示使用者人工
審閱草稿**，確認後執行：

```bash
.venv/bin/python rules.py adopt <rule_id>
```

adopt 會先 lint，通過才搬進 `config/<域>/knowhow/`；草稿標記
`NEEDS_PY` 表示超出宣告式能力，須改寫成 knowhow_py 程式式規則。
全程紀錄：`drafts/LOG.md`（怎麼來的）＋ `rules_history/`（何時生效）。
agent 不得跳過 draft/adopt 直接把 LLM 生成的規則寫入 knowhow。

## 不可破壞的保證

1. 閘門只用確定性規則；LLM 只能進顧問區。
2. 同一 DDL＋規則集，checking rule ID 結果必須一致。
3. DDL 個案補充設定放 `config/<域>/cases/`；Domain 知識放 `config/<域>/`
   （knowhow／naming／ssot／erd／flows）；Python 規則放
   `config/Common/knowhow_py/`；Mermaid ER diagram 放 `config/<域>/erd/`。引擎只提供機制。
4. `run.py` 是唯一日常入口；預設掃 `input/`，可用 `DATAVAL_INPUT_DIR` 切換範例。
   每個 data subject 需要**三件必備輸入**（`<名>.sql`、`relations.yaml`、
   `context.md`），一 subject 一資料夾（`input/<名>/`，格式見 `input/README.md`）。
   **樣本 `samples/<表>.csv` 是選填**——沒有樣本仍會產生報告，只是樣本相關檢查
   （型別對樣本、join key 編碼、基數實檢）略過。
   `run.py` 先做前置檢核，缺**必備件**的 DDL **不會產生報告**並以 exit code 2 結束；
   此時 agent 必須把 `reports/<名>.precheck.md` 的缺件明細轉告使用者、
   請使用者補齊後重跑，**不可**自行代填語意描述或關聯。樣本缺漏只是警告，不需補齊。
5. 改動後執行 checking verbs、architecture、golden 三組測試；只有刻意改變結果時才
   使用 `tests/golden_test.py --update`。
