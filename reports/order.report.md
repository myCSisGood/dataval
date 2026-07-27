# 資料設計驗證報告
_產生時間 2026-07-27T16:09:31.628775Z_<br>
**判定：✅ 合規**（會擋項目 0）<br>
通過 33 · 警告 5 · 失敗 0 · 略過 5 · 提示 3<br>
閘門區 39 項 · 顧問區 7 項<br>
> 方言 clickhouse · 表數 2 · 載入 skill 26 條
> 驗證 bundle `44c8505165ab5c65`（含規則、validator 與依賴版本）

## Checking rule ID 摘要
- ❌ 擋下：（無）
- ⚠️ 警告：`SKILL.naming_glossary`、`SKILL.ssot_authority`、`SSOT.UNREGISTERED_SUBJECT`
- ✅ 通過：`BUSINESS_KEY.METADATA`、`DOMAIN.SCOPE`、`LINEAGE.COLUMN_EXISTS`、`LINEAGE.CYCLE`、`LINEAGE.DOMAIN_SCOPE`、`LINEAGE.METADATA`、`LINEAGE.TYPE_COMPATIBILITY`、`LINEAGE.UPSTREAM_EXISTS`、`PRODGRAPH.CARDINALITY_CONFLICT`、`PRODGRAPH.CYCLE`、`PRODUCTION.NAMING_CONSISTENCY`、`PRODUCTION.SCOPE`、`SKILL.bp_datetime_timezone`、`SKILL.bp_lowcardinality_status`、`SKILL.bp_money_decimal`、`SKILL.bp_no_float`、`SKILL.naming_column_case`、`SKILL.naming_columns_commented`、`SKILL.naming_identifier_length`、`SKILL.naming_pk_suffix`、`SKILL.naming_reserved_words`、`SKILL.naming_table_snake_case`、`SKILL.no_future_event_time`、`SKILL.ssot_fact_duplication`、`SKILL.ssot_join_keys`、`SKILL.ssot_pii_amount_split`、`SKILL.structural_audit_columns`、`SKILL.structural_business_key`、`SKILL.structural_engine_mergetree`、`SKILL.structural_key_not_nullable`、`SKILL.structural_order_by`、`SKILL.structural_type_sample`
- ℹ️ 未實檢／略過：`SKILL.structural_fk_resolves`
- 💡 顧問：`CONCEPT.SUBJECT`、`FLOW.CONTEXT`、`PRODGRAPH.IMPACT`、`SKILL.best_practice_semantic`、`SKILL.naming_semantic`、`SKILL.ssot_semantic`

## 規則涵蓋清單
> 宣告域（context.md）：CRM · config 可用域：BLM、CRM、Common、FCM、PLM、SCM
> 涵蓋：載入並執行 **26** 條 ／ config 共 **39** 條

### ✅ 已載入並執行（26 條）
- `SKILL.best_practice_semantic`（Common）→ 💡 顧問
- `SKILL.bp_datetime_timezone`（Common）→ ✅ 通過
- `SKILL.bp_lowcardinality_status`（Common）→ ✅ 通過
- `SKILL.bp_money_decimal`（Common）→ ✅ 通過
- `SKILL.bp_no_float`（Common）→ ✅ 通過
- `SKILL.naming_column_case`（Common）→ ✅ 通過
- `SKILL.naming_columns_commented`（Common）→ ✅ 通過
- `SKILL.naming_glossary`（Common）→ ⚠️ 警告
- `SKILL.naming_identifier_length`（Common）→ ✅ 通過
- `SKILL.naming_pk_suffix`（Common）→ ✅ 通過
- `SKILL.naming_reserved_words`（Common）→ ✅ 通過
- `SKILL.naming_semantic`（Common）→ 💡 顧問
- `SKILL.naming_table_snake_case`（Common）→ ✅ 通過
- `SKILL.no_future_event_time`（Common）→ ✅ 通過
- `SKILL.ssot_authority`（Common）→ ⚠️ 警告
- `SKILL.ssot_fact_duplication`（Common）→ ✅ 通過
- `SKILL.ssot_join_keys`（Common）→ ✅ 通過
- `SKILL.ssot_pii_amount_split`（Common）→ ✅ 通過
- `SKILL.ssot_semantic`（Common）→ 💡 顧問
- `SKILL.structural_audit_columns`（Common）→ ✅ 通過
- `SKILL.structural_business_key`（Common）→ ✅ 通過
- `SKILL.structural_engine_mergetree`（Common）→ ✅ 通過
- `SKILL.structural_fk_resolves`（Common）→ ℹ️ 未實檢／略過
- `SKILL.structural_key_not_nullable`（Common）→ ✅ 通過
- `SKILL.structural_order_by`（Common）→ ✅ 通過
- `SKILL.structural_type_sample`（Common）→ ✅ 通過

### ⏭️ 未載入：所屬域未在 context.md 宣告（13 條）
- **BLM**：`SKILL.blm_baseline`
- **FCM**：`SKILL.fcm_baseline`、`SKILL.fcm_master_data_semantic`
- **PLM**：`SKILL.plm_bom_needs_quantity`、`SKILL.plm_bom_structural_integrity`、`SKILL.plm_engineering_change`、`SKILL.plm_lifecycle_stage`、`SKILL.plm_part_master_baseline`、`SKILL.plm_revision_versioning`
- **SCM**：`SKILL.scm_grn_needs_po`、`SKILL.scm_po_needs_supplier`、`SKILL.scm_supplier_baseline`、`SKILL.scm_supply_semantic`
> 若這些域也應納入檢查，請在 context.md front-matter 的 `domains` 補上該域後重跑。

### ⚠️ 空的域（資料夾存在但無任何規則）
- CRM

## Lineage 關聯
> 關係來自 relations.yaml，並參照 ER diagram；兩者都是設計宣告，不代表已觀測到 runtime lineage。

| 來源 | 目標 | 欄位映射 | 性質 |
|---|---|---|---|
| `local.orders` | `order_items` | `order_id` → `order_id` | YAML 宣告＋ER 對應 |
| `CRM.dim_customer` | `orders` | `customer_id` → `customer_id` | YAML 明確宣告 |

## 本次卡控摘要（被哪些規則卡下來）

**警告（放行但需注意）：**
- `SKILL.naming_glossary` 命名對照詞彙字典 → order_items
- `SKILL.ssot_authority` 權威表在場檢視 → dim_customer、dim_product
- `SSOT.UNREGISTERED_SUBJECT` 未登錄主體候選 'order_item' → order_items、orders

## 結構（欄位／型別／約束）

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ⏭️ | 閘門 | `SKILL.structural_fk_resolves` | `(schema)` | structural_fk_resolves：本次 schema 沒有可檢查的 FK。 | skill |
| ℹ️ | 顧問 | `FLOW.CONTEXT` | `order_items` | 此表位於 E2E 流程「訂單到營收」第 3/4 站；上游站點：orders；下游站點：營收日報。設計變更時請沿流程確認上下游影響。 | rule |
| ℹ️ | 顧問 | `FLOW.CONTEXT` | `orders` | 此表位於 E2E 流程「訂單到營收」第 2/4 站；上游站點：結帳服務；下游站點：order_items。設計變更時請沿流程確認上下游影響。 | rule |
| ✅ | 閘門 | `BUSINESS_KEY.METADATA` | `(schema)` | Business key metadata 已驗證：['order_items', 'orders']。 | rule |
| ✅ | 閘門 | `DOMAIN.SCOPE` | `(domains)` | Domain 範圍已明確：['CRM', 'Common']。 | rule |
| ✅ | 閘門 | `SKILL.structural_audit_columns` | `2 表` | 表應有稽核欄位（created_at / updated_at）：2 表全數通過（orders、order_items） <br>_理由：稽核欄位支撐血緣追蹤與變更歷史。_ | skill |
| ✅ | 閘門 | `SKILL.structural_business_key` | `2 表` | 表必須有 Business Key：2 表全數通過（orders、order_items） <br>_理由：每張表需要穩定的業務識別鍵，才能被正確引用、合併與去重。 ClickHouse ORDER BY 只是物理排序鍵，不等於業務唯一性。_ | skill |
| ✅ | 閘門 | `SKILL.structural_engine_mergetree` | `2 表` | 明細表引擎須為 MergeTree 系列（ClickHouse）：2 表全數通過（orders、order_items） <br>_理由：明細層資料應使用 MergeTree 家族引擎（MergeTree / ReplacingMergeTree 等）。_ | skill |
| ✅ | 閘門 | `SKILL.structural_key_not_nullable` | `2 表` | 鍵欄位不可為 Nullable：2 表全數通過（orders、order_items） <br>_理由：主鍵／排序鍵為 Nullable 會破壞合併與去重語意，並帶來額外標記欄位開銷。_ | skill |
| ✅ | 閘門 | `SKILL.structural_order_by` | `2 表` | 表必須有 ORDER BY（ClickHouse）：2 表全數通過（orders、order_items） <br>_理由：MergeTree 家族依 ORDER BY 建立稀疏索引，缺少它等於放棄索引。_ | skill |
| ✅ | 閘門 | `SKILL.structural_type_sample` | `(sample)` | 型別對樣本檢查：135 個樣本值全數通過。 | skill |

## 命名規則

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ⚠️ | 閘門 | `SKILL.naming_glossary` | `order_items` | 命名對照詞彙字典：欄位用到別名：order_item_id（'item'） <br>**期望** 使用正規詞 ｜ **實際** order_item_id 用了別名 'item' <br>**修法** order_item_id 改用 'product' <br>_理由：欄位命名應使用公司認可的標準詞，避免縮寫與同義異名造成理解成本與整合困難。 此規則對照 config/glossary.yaml 的詞彙字典做檢查，比寫一堆正則更易維護。_ | skill |
| ⏭️ | 顧問 | `SKILL.naming_semantic` | `(skill)` | 未接 LLM，略過語意卡控「跨表命名語意一致性（語意）」。 | llm |
| ✅ | 閘門 | `PRODUCTION.NAMING_CONSISTENCY` | `(production)` | 新設計命名與 production 基準一致。 | rule |
| ✅ | 閘門 | `SKILL.naming_column_case` | `2 表` | 欄位名須為 snake_case 全小寫：2 表全數通過（orders、order_items） <br>_理由：欄位命名樣式一致是資料字典與自動化的基礎。_ | skill |
| ✅ | 閘門 | `SKILL.naming_columns_commented` | `2 表` | 所有欄位必須有 COMMENT 註解：2 表全數通過（orders、order_items） <br>_理由：欄位註解是資料字典的最小單位，中介資料平台會直接讀取。_ | skill |
| ✅ | 閘門 | `SKILL.naming_glossary` | `1 表` | 命名對照詞彙字典：1 表全數通過（orders） <br>_理由：欄位命名應使用公司認可的標準詞，避免縮寫與同義異名造成理解成本與整合困難。 此規則對照 config/glossary.yaml 的詞彙字典做檢查，比寫一堆正則更易維護。_ | skill |
| ✅ | 閘門 | `SKILL.naming_identifier_length` | `2 表` | 識別字長度不超過 64 字元：2 表全數通過（orders、order_items） <br>_理由：過長的表名／欄名不利閱讀與部分工具相容。_ | skill |
| ✅ | 閘門 | `SKILL.naming_pk_suffix` | `2 表` | 主鍵欄位建議以 _id 結尾：2 表全數通過（orders、order_items） <br>_理由：可預測的鍵名（x_id）讓 join 推斷與理解更容易。_ | skill |
| ✅ | 閘門 | `SKILL.naming_reserved_words` | `2 表` | 欄位名避免 SQL 保留字：2 表全數通過（orders、order_items） <br>_理由：使用保留字當欄名需要跳脫，易出錯。_ | skill |
| ✅ | 閘門 | `SKILL.naming_table_snake_case` | `2 表` | 表名須為 snake_case 全小寫：2 表全數通過（orders、order_items） <br>_理由：一致的表名讓資產可預測、可被工具處理。_ | skill |

## 最佳實踐

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ⏭️ | 顧問 | `SKILL.best_practice_semantic` | `(skill)` | 未接 LLM，略過語意卡控「依表型態的最佳實踐建議（語意）」。 | llm |
| ✅ | 閘門 | `SKILL.bp_datetime_timezone` | `2 表` | DateTime 應標明時區：2 表全數通過（orders、order_items） <br>_理由：時區不明的時間在跨區情境無法正確比較，應以 DateTime('UTC') 或註解標明。_ | skill |
| ✅ | 閘門 | `SKILL.bp_lowcardinality_status` | `2 表` | status 欄位須用 LowCardinality（ClickHouse）：2 表全數通過（orders、order_items） <br>_理由：低基數高重複欄位以 LowCardinality 儲存可大幅省空間與記憶體。_ | skill |
| ✅ | 閘門 | `SKILL.bp_money_decimal` | `2 表` | 金額欄位必須用 Decimal：2 表全數通過（orders、order_items） <br>_理由：名稱含 amount/price/cost/fee 等的金額欄位，使用浮點數會導致對帳不平。_ | skill |
| ✅ | 閘門 | `SKILL.bp_no_float` | `2 表` | 不可使用 Float 型別：2 表全數通過（orders、order_items） <br>_理由：Float 不適合需要精確比較與彙總的數值。_ | skill |
| ✅ | 閘門 | `SKILL.no_future_event_time` | `(schema)` | no_future_event_time：已執行，未發現違規。 | skill |

## 單一真實源（跨域）

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ⚠️ | 閘門 | `SKILL.ssot_authority` | `dim_customer` | 權威表在場檢視：'customer' 的權威表不在本次 DDL。 <br>_理由：若它屬於另一 domain 的 schema 則屬正常。_ | skill |
| ⚠️ | 閘門 | `SKILL.ssot_authority` | `dim_product` | 權威表在場檢視：'product' 的權威表不在本次 DDL。 <br>_理由：若它屬於另一 domain 的 schema 則屬正常。_ | skill |
| ⚠️ | 閘門 | `SSOT.UNREGISTERED_SUBJECT` | `order_items` | 未登錄主體候選 'order_item'：此表看似其權威表（證據欄位 ['quantity', 'unit_price']），但 SSOT registry 尚未登錄。建議先登錄再上線。 <br>**期望** 'order_item' 已登錄於 ssot.registry ｜ **實際** registry 查無此主體 <br>**修法** 於 config/default.yaml 的 ssot.registry 登錄 'order_item'（權威表 order_items） <br>_理由：新 data subject 應先登錄權威表，否則跨域 SSOT 硬檢查無法涵蓋它。可由顧問區產 registry 草稿、人工確認後寫回。_ | rule |
| ⚠️ | 閘門 | `SSOT.UNREGISTERED_SUBJECT` | `orders` | 未登錄主體候選 'order'：此表看似其權威表（證據欄位 ['status', 'currency', 'total_amount']），但 SSOT registry 尚未登錄。建議先登錄再上線。 <br>**期望** 'order' 已登錄於 ssot.registry ｜ **實際** registry 查無此主體 <br>**修法** 於 config/default.yaml 的 ssot.registry 登錄 'order'（權威表 orders） <br>_理由：新 data subject 應先登錄權威表，否則跨域 SSOT 硬檢查無法涵蓋它。可由顧問區產 registry 草稿、人工確認後寫回。_ | rule |
| ⏭️ | 顧問 | `SKILL.ssot_semantic` | `(skill)` | 未接 LLM，略過語意卡控「SSOT 候選衝突偵測（語意）」。 | llm |
| ✅ | 閘門 | `PRODUCTION.SCOPE` | `(production)` | 已參照 production domain：['CRM']。 | rule |
| ✅ | 閘門 | `SKILL.ssot_fact_duplication` | `(schema)` | ssot_fact_duplication：已執行，未發現違規。 | skill |
| ✅ | 閘門 | `SKILL.ssot_join_keys` | `order_id` | Join key 型別一致：'order_id' 於 2 表型別一致。 | skill |
| ✅ | 閘門 | `SKILL.ssot_pii_amount_split` | `2 表` | 個資與金額應分表存放：2 表全數通過（orders、order_items） <br>_理由：PII 與金額混存使權限難分級、真實源歸屬模糊。_ | skill |

## 資料設計概念（主體性）

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ⏭️ | 顧問 | `CONCEPT.SUBJECT` | `(schema)` | 未設定 LLM，略過主體性概念層。 | llm |

## Lineage 關聯治理

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ℹ️ | 顧問 | `PRODGRAPH.IMPACT` | `crm.orders` | 正式區有 1 處依賴此表：CRM/order（order_items.order_id）。此表的結構或語意變更會影響這些 subject。 <br>**修法** 變更前通知依賴方；破壞性變更應開新表版本而非原地修改。 | rule |
| ✅ | 閘門 | `LINEAGE.COLUMN_EXISTS` | `(lineage)` | 所有 lineage 欄位映射都可解析。 | rule |
| ✅ | 閘門 | `LINEAGE.CYCLE` | `(lineage)` | local lineage 未形成循環。 | rule |
| ✅ | 閘門 | `LINEAGE.DOMAIN_SCOPE` | `(lineage)` | 所有外部上游 domain 都已明確選取。 | rule |
| ✅ | 閘門 | `LINEAGE.METADATA` | `(lineage)` | relations.yaml 的 lineage 格式與目標表有效。 | rule |
| ✅ | 閘門 | `LINEAGE.TYPE_COMPATIBILITY` | `(lineage)` | 所有 lineage 欄位基本型別相容。 | rule |
| ✅ | 閘門 | `LINEAGE.UPSTREAM_EXISTS` | `(lineage)` | 所有宣告的上游資料表都存在。 | rule |
| ✅ | 閘門 | `PRODGRAPH.CARDINALITY_CONFLICT` | `(全域關聯圖)` | 關聯宣告與正式區既有 subject 的基數一致。 | rule |
| ✅ | 閘門 | `PRODGRAPH.CYCLE` | `(全域關聯圖)` | 加入本 subject 後全域關聯圖無循環。 | rule |
