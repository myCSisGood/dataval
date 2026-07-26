# Agent 操作規範

這是 ClickHouse DDL 資料治理工具。完整使用方式見 `README.md`；新增規則時再讀
`SKILL_AUTHORING.md`。

## 驗證 DDL

使用者要求驗證、產生報告或跑檢查時：

```bash
.venv/bin/python run.py
```

新 DDL 放在 `input/<名稱>.sql`；`input/` 不放其他設定。同一個名稱的治理資訊集中在
`config/cases/<名稱>.yaml`，可包含 `sample_data`、`context`、`domains`、
`business_keys` 與 `lineage`。

同名 Mermaid ER diagram 放在 `config/er_diagrams/<名稱>.mmd`。ER 關係只能轉成
lineage 顧問候選；case config 沒有 `lineage` 明確宣告時，不得把 ER association 說成已確認
的資料流向。

`Common` 永遠載入；其他 domain 只由 case config 的 `domains` 指定。不得把 ClickHouse
`ORDER BY` 或 `PRIMARY KEY` 當成 Business Key。外部 lineage 來源必須存在於已選
domain 的 `production/`；沒有 YAML 時只能把推測稱為建議，不能說成已確認血緣。

## 補完顧問區

未設定本地 LLM 時，`run.py` 仍會產生 Markdown、JSON、HTML 與
`advisory_prompt.md`；HTML 會清楚標示語意規則待補完。報告依代表性 domain 分類到
`reports/<域>/`（`advisory_prompt.md` 同在此資料夾）。需要補完時 Agent 應：

1. 讀取 `reports/<域>/<名稱>.advisory_prompt.md`。
2. 依其中格式產生 `advisory_result.json`，放在**與 prompt 同一個資料夾**
   （`reports/<域>/<名稱>.advisory_result.json`；放在 `reports/` 根也相容）。
3. 執行 `.venv/bin/python merge_advisory.py`。
4. 確認更新後的 `.report.html`，閘門結果必須不變。

**完整的 JSON 格式與驗證規則已內嵌在生成的 `advisory_prompt.md` 裡**（欄位、
非空字串、skill id 樣式等逐條列出），照它做即可，不必另外查
`config/_engine/advisory_result.schema.json` 或本檔——本檔只講流程，格式以 prompt 為準。

顧問建議一律是 `info`，永遠不能改變合規判定。合併程式會逐項比較合併前後的
gating findings，不一致就拒絕寫入。

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
3. DDL 個案設定放 `config/<域>/cases/`；Domain 知識放 `config/domainss/<域>/`（knowhow／naming／erd／flows）；Python 規則放
   `config/domainss/Common/knowhow_py/`；Mermaid ER diagram 放 `config/er_diagrams/`。引擎只提供機制。
4. `run.py` 是唯一日常入口；預設掃 `input/`，可用 `DATAVAL_INPUT_DIR` 切換範例。
   每個 data subject 需要**四件輸入**，一 subject 一資料夾
   （`input/<名>/`：`<名>.sql`、`samples/<表>.csv`、`relations.yaml`、
   `context.md`，格式見 `input/README.md`）。
   `run.py` 先做前置檢核，缺件的 DDL **不會產生報告**並以 exit code 2 結束；
   此時 agent 必須把 `reports/<名>.precheck.md` 的缺件明細轉告使用者、
   請使用者補齊後重跑，**不可**自行代填樣本或語意描述。
5. 改動後執行 checking verbs、architecture、golden 三組測試；只有刻意改變結果時才
   使用 `tests/golden_test.py --update`。
