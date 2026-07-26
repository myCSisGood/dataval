# 資料設計驗證報告
_產生時間 2026-07-25T09:06:54.370287Z_<br>
**判定：❌ 不合規**（會擋項目 11）<br>
通過 25 · 警告 12 · 失敗 11 · 略過 6 · 提示 1<br>
閘門區 50 項 · 顧問區 5 項<br>
> 方言 clickhouse · 表數 3 · 載入 skill 26 條

## Checking rule ID 摘要
- ❌ 擋下：`LINEAGE.TYPE_COMPATIBILITY`、`SKILL.bp_money_decimal`、`SKILL.bp_no_float`、`SKILL.naming_column_case`、`SKILL.naming_columns_commented`、`SKILL.ssot_authority`、`SKILL.ssot_join_keys`
- ⚠️ 警告：`DOMAIN.SCOPE`、`SKILL.bp_datetime_timezone`、`SKILL.ssot_fact_duplication`、`SKILL.ssot_pii_amount_split`、`SKILL.structural_audit_columns`、`SSOT.UNREGISTERED_SUBJECT`
- ✅ 通過：`BUSINESS_KEY.METADATA`、`LINEAGE.COLUMN_EXISTS`、`LINEAGE.CYCLE`、`LINEAGE.DOMAIN_SCOPE`、`LINEAGE.METADATA`、`LINEAGE.UPSTREAM_EXISTS`、`PRODGRAPH.CARDINALITY_CONFLICT`、`PRODGRAPH.CYCLE`、`SKILL.bp_lowcardinality_status`、`SKILL.naming_glossary`、`SKILL.naming_identifier_length`、`SKILL.naming_pk_suffix`、`SKILL.naming_reserved_words`、`SKILL.naming_table_snake_case`、`SKILL.no_future_event_time`、`SKILL.structural_business_key`、`SKILL.structural_engine_mergetree`、`SKILL.structural_key_not_nullable`、`SKILL.structural_order_by`、`SKILL.structural_type_sample`
- ℹ️ 未實檢／略過：`PRODUCTION.SCOPE`、`SKILL.structural_fk_resolves`
- 💡 顧問：`CONCEPT.SUBJECT`、`PRODGRAPH.IMPACT`、`SKILL.best_practice_semantic`、`SKILL.naming_semantic`、`SKILL.ssot_semantic`

## Lineage 關聯
> 關係來自 case config 的 lineage；這是設計宣告，不代表已觀測到執行血緣。

| 來源 | 目標 | 欄位映射 | 性質 |
|---|---|---|---|
| `local.dim_customer` | `billing_event` | `customer_id` → `customer_id` | YAML 明確宣告 |
| `local.dim_customer` | `subscription` | `customer_id` → `customer_id` | YAML 明確宣告 |

## 本次卡控摘要（被哪些規則卡下來）
**擋下（不合規的原因）：**
- `LINEAGE.TYPE_COMPATIBILITY` LINEAGE.TYPE_COMPATIBILITY → 擋下 local.dim_customer.customer_id → subscription.customer_id（lineage 來源與目標欄位型別不相容。）
- `SKILL.bp_money_decimal` 金額欄位必須用 Decimal → 擋下 billing_event、subscription（金額類欄位使用了 float：['amount']）
- `SKILL.bp_no_float` 不可使用 Float 型別 → 擋下 billing_event、subscription（使用了不建議的型別 Float：['amount']）
- `SKILL.naming_column_case` 欄位名須為 snake_case 全小寫 → 擋下 subscription（欄位名不符樣式：['MonthlyPrice']）
- `SKILL.naming_columns_commented` 所有欄位必須有 COMMENT 註解 → 擋下 billing_event、dim_customer、subscription（欄位缺少註解：['event_id', 'customer_id', 'amount', 'occurred_at']）
- `SKILL.ssot_authority` 權威唯一性 → 擋下 subscription（此表重複承載 'customer' 的權威屬性 ['customer_email']（權威表：dim_customer））
- `SKILL.ssot_join_keys` Join key 型別一致 → 擋下 customer_id（'customer_id' 跨表型別不一致 [('dim_customer', 'int'), ('subscripti）

**警告（放行但需注意）：**
- `DOMAIN.SCOPE` DOMAIN.SCOPE → (domains)
- `SKILL.bp_datetime_timezone` DateTime 應標明時區 → billing_event、dim_customer、subscription
- `SKILL.ssot_authority` 權威表在場檢視 → dim_product
- `SKILL.ssot_fact_duplication` 事實重複 → customer_email
- `SKILL.ssot_join_keys` Join key 值編碼 → customer_id
- `SKILL.ssot_pii_amount_split` 個資與金額應分表存放 → subscription
- `SKILL.structural_audit_columns` 表應有稽核欄位（created_at / updated_at） → billing_event、subscription
- `SSOT.UNREGISTERED_SUBJECT` 未登錄主體候選 'event' → billing_event、subscription

## 結構（欄位／型別／約束）

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ⚠️ | 閘門 | `DOMAIN.SCOPE` | `(domains)` | 未指定 domain，依安全預設只載入 Common。 <br>**期望** 在 config/cases/<DDL名>.yaml 明確指定業務 domain ｜ **實際** 未指定 <br>**修法** 新增 domains；若確定只需共用規則可保持現狀 | rule |
| ⚠️ | 閘門 | `SKILL.structural_audit_columns` | `billing_event` | 表應有稽核欄位（created_at / updated_at）：缺少必要欄位 'created_at'；缺少必要欄位 'updated_at' <br>**期望** 表上有欄位 created_at；表上有欄位 updated_at ｜ **實際** 欄位不存在 <br>**修法** 新增欄位 created_at；新增欄位 updated_at <br>_理由：稽核欄位支撐血緣追蹤與變更歷史。_ | skill |
| ⚠️ | 閘門 | `SKILL.structural_audit_columns` | `subscription` | 表應有稽核欄位（created_at / updated_at）：缺少必要欄位 'updated_at' <br>**期望** 表上有欄位 updated_at ｜ **實際** 欄位不存在 <br>**修法** 新增欄位 updated_at <br>_理由：稽核欄位支撐血緣追蹤與變更歷史。_ | skill |
| ⏭️ | 閘門 | `SKILL.structural_fk_resolves` | `(schema)` | structural_fk_resolves：本次 schema 沒有可檢查的 FK。 | skill |
| ✅ | 閘門 | `BUSINESS_KEY.METADATA` | `(schema)` | Business key metadata 已驗證：['billing_event', 'dim_customer', 'subscription']。 | rule |
| ✅ | 閘門 | `SKILL.structural_audit_columns` | `1 表` | 表應有稽核欄位（created_at / updated_at）：1 表全數通過（dim_customer） <br>_理由：稽核欄位支撐血緣追蹤與變更歷史。_ | skill |
| ✅ | 閘門 | `SKILL.structural_business_key` | `3 表` | 表必須有 Business Key：3 表全數通過（dim_customer、subscription、billing_event） <br>_理由：每張表需要穩定的業務識別鍵，才能被正確引用、合併與去重。 ClickHouse ORDER BY 只是物理排序鍵，不等於業務唯一性。_ | skill |
| ✅ | 閘門 | `SKILL.structural_engine_mergetree` | `3 表` | 明細表引擎須為 MergeTree 系列（ClickHouse）：3 表全數通過（dim_customer、subscription、billing_event） <br>_理由：明細層資料應使用 MergeTree 家族引擎（MergeTree / ReplacingMergeTree 等）。_ | skill |
| ✅ | 閘門 | `SKILL.structural_key_not_nullable` | `3 表` | 鍵欄位不可為 Nullable：3 表全數通過（dim_customer、subscription、billing_event） <br>_理由：主鍵／排序鍵為 Nullable 會破壞合併與去重語意，並帶來額外標記欄位開銷。_ | skill |
| ✅ | 閘門 | `SKILL.structural_order_by` | `3 表` | 表必須有 ORDER BY（ClickHouse）：3 表全數通過（dim_customer、subscription、billing_event） <br>_理由：MergeTree 家族依 ORDER BY 建立稀疏索引，缺少它等於放棄索引。_ | skill |
| ✅ | 閘門 | `SKILL.structural_type_sample` | `(sample)` | 型別對樣本檢查：48 個樣本值全數通過。 | skill |

## 命名規則

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ❌ | 閘門 | `SKILL.naming_column_case` | `subscription` | 欄位名須為 snake_case 全小寫：欄位名不符樣式：['MonthlyPrice'] <br>**期望** 符合 /[a-z][a-z0-9_]*/ ｜ **實際** MonthlyPrice <br>**修法** 依樣式重新命名（snake_case 全小寫） <br>_理由：欄位命名樣式一致是資料字典與自動化的基礎。_ | skill |
| ❌ | 閘門 | `SKILL.naming_columns_commented` | `billing_event` | 所有欄位必須有 COMMENT 註解：欄位缺少註解：['event_id', 'customer_id', 'amount', 'occurred_at'] <br>**期望** 每個欄位都有 COMMENT ｜ **實際** 4 欄無註解 ['event_id', 'customer_id', 'amount', 'occurred_at'] <br>**修法** 為每個欄位補上 COMMENT '說明' <br>_理由：欄位註解是資料字典的最小單位，中介資料平台會直接讀取。_ | skill |
| ❌ | 閘門 | `SKILL.naming_columns_commented` | `dim_customer` | 所有欄位必須有 COMMENT 註解：欄位缺少註解：['customer_id', 'customer_name', 'customer_email', 'customer_tier', 'created_at', 'updated_at'] <br>**期望** 每個欄位都有 COMMENT ｜ **實際** 6 欄無註解 ['customer_id', 'customer_name', 'customer_email', 'customer_tier', 'created_at', 'updated_at'] <br>**修法** 為每個欄位補上 COMMENT '說明' <br>_理由：欄位註解是資料字典的最小單位，中介資料平台會直接讀取。_ | skill |
| ❌ | 閘門 | `SKILL.naming_columns_commented` | `subscription` | 所有欄位必須有 COMMENT 註解：欄位缺少註解：['subscription_id', 'customer_id', 'customer_email', 'MonthlyPrice', 'started_at', 'created_at'] <br>**期望** 每個欄位都有 COMMENT ｜ **實際** 6 欄無註解 ['subscription_id', 'customer_id', 'customer_email', 'MonthlyPrice', 'started_at', 'created_at'] <br>**修法** 為每個欄位補上 COMMENT '說明' <br>_理由：欄位註解是資料字典的最小單位，中介資料平台會直接讀取。_ | skill |
| ⏭️ | 顧問 | `SKILL.naming_semantic` | `(skill)` | 未接 LLM，略過語意卡控「跨表命名語意一致性（語意）」。 | llm |
| ✅ | 閘門 | `SKILL.naming_column_case` | `2 表` | 欄位名須為 snake_case 全小寫：2 表全數通過（dim_customer、billing_event） <br>_理由：欄位命名樣式一致是資料字典與自動化的基礎。_ | skill |
| ✅ | 閘門 | `SKILL.naming_glossary` | `3 表` | 命名對照詞彙字典：3 表全數通過（dim_customer、subscription、billing_event） <br>_理由：欄位命名應使用公司認可的標準詞，避免縮寫與同義異名造成理解成本與整合困難。 此規則對照 config/glossary.yaml 的詞彙字典做檢查，比寫一堆正則更易維護。_ | skill |
| ✅ | 閘門 | `SKILL.naming_identifier_length` | `3 表` | 識別字長度不超過 64 字元：3 表全數通過（dim_customer、subscription、billing_event） <br>_理由：過長的表名／欄名不利閱讀與部分工具相容。_ | skill |
| ✅ | 閘門 | `SKILL.naming_pk_suffix` | `3 表` | 主鍵欄位建議以 _id 結尾：3 表全數通過（dim_customer、subscription、billing_event） <br>_理由：可預測的鍵名（x_id）讓 join 推斷與理解更容易。_ | skill |
| ✅ | 閘門 | `SKILL.naming_reserved_words` | `3 表` | 欄位名避免 SQL 保留字：3 表全數通過（dim_customer、subscription、billing_event） <br>_理由：使用保留字當欄名需要跳脫，易出錯。_ | skill |
| ✅ | 閘門 | `SKILL.naming_table_snake_case` | `3 表` | 表名須為 snake_case 全小寫：3 表全數通過（dim_customer、subscription、billing_event） <br>_理由：一致的表名讓資產可預測、可被工具處理。_ | skill |

## 最佳實踐

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ❌ | 閘門 | `SKILL.bp_money_decimal` | `billing_event` | 金額欄位必須用 Decimal：金額類欄位使用了 float：['amount'] <br>**期望** 金額類欄位為 Decimal(P,S) ｜ **實際** amount:Float64 <br>**修法** amount 改為 Decimal(18,2) <br>_理由：名稱含 amount/price/cost/fee 等的金額欄位，使用浮點數會導致對帳不平。_ | skill |
| ❌ | 閘門 | `SKILL.bp_money_decimal` | `subscription` | 金額欄位必須用 Decimal：金額類欄位使用了 float：['MonthlyPrice'] <br>**期望** 金額類欄位為 Decimal(P,S) ｜ **實際** MonthlyPrice:Float64 <br>**修法** MonthlyPrice 改為 Decimal(18,2) <br>_理由：名稱含 amount/price/cost/fee 等的金額欄位，使用浮點數會導致對帳不平。_ | skill |
| ❌ | 閘門 | `SKILL.bp_no_float` | `billing_event` | 不可使用 Float 型別：使用了不建議的型別 Float：['amount'] <br>**期望** 不使用 Float ｜ **實際** amount:Float64 <br>**修法** 數值精確性需求改用 Decimal(P,S) <br>_理由：Float 不適合需要精確比較與彙總的數值。_ | skill |
| ❌ | 閘門 | `SKILL.bp_no_float` | `subscription` | 不可使用 Float 型別：使用了不建議的型別 Float：['MonthlyPrice'] <br>**期望** 不使用 Float ｜ **實際** MonthlyPrice:Float64 <br>**修法** 數值精確性需求改用 Decimal(P,S) <br>_理由：Float 不適合需要精確比較與彙總的數值。_ | skill |
| ⚠️ | 閘門 | `SKILL.bp_datetime_timezone` | `billing_event` | DateTime 應標明時區：DateTime 未標明時區：['occurred_at'] <br>**期望** DateTime('UTC') 或註解標明時區 ｜ **實際** occurred_at <br>**修法** 改用 DateTime('UTC') 或於 COMMENT 註明時區 <br>_理由：時區不明的時間在跨區情境無法正確比較，應以 DateTime('UTC') 或註解標明。_ | skill |
| ⚠️ | 閘門 | `SKILL.bp_datetime_timezone` | `dim_customer` | DateTime 應標明時區：DateTime 未標明時區：['created_at', 'updated_at'] <br>**期望** DateTime('UTC') 或註解標明時區 ｜ **實際** created_at；updated_at <br>**修法** 改用 DateTime('UTC') 或於 COMMENT 註明時區 <br>_理由：時區不明的時間在跨區情境無法正確比較，應以 DateTime('UTC') 或註解標明。_ | skill |
| ⚠️ | 閘門 | `SKILL.bp_datetime_timezone` | `subscription` | DateTime 應標明時區：DateTime 未標明時區：['started_at', 'created_at'] <br>**期望** DateTime('UTC') 或註解標明時區 ｜ **實際** started_at；created_at <br>**修法** 改用 DateTime('UTC') 或於 COMMENT 註明時區 <br>_理由：時區不明的時間在跨區情境無法正確比較，應以 DateTime('UTC') 或註解標明。_ | skill |
| ⏭️ | 顧問 | `SKILL.best_practice_semantic` | `(skill)` | 未接 LLM，略過語意卡控「依表型態的最佳實踐建議（語意）」。 | llm |
| ✅ | 閘門 | `SKILL.bp_lowcardinality_status` | `3 表` | status 欄位須用 LowCardinality（ClickHouse）：3 表全數通過（dim_customer、subscription、billing_event） <br>_理由：低基數高重複欄位以 LowCardinality 儲存可大幅省空間與記憶體。_ | skill |
| ✅ | 閘門 | `SKILL.bp_money_decimal` | `1 表` | 金額欄位必須用 Decimal：1 表全數通過（dim_customer） <br>_理由：名稱含 amount/price/cost/fee 等的金額欄位，使用浮點數會導致對帳不平。_ | skill |
| ✅ | 閘門 | `SKILL.bp_no_float` | `1 表` | 不可使用 Float 型別：1 表全數通過（dim_customer） <br>_理由：Float 不適合需要精確比較與彙總的數值。_ | skill |
| ✅ | 閘門 | `SKILL.no_future_event_time` | `(schema)` | no_future_event_time：已執行，未發現違規。 | skill |

## 單一真實源（跨域）

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ❌ | 閘門 | `SKILL.ssot_authority` | `subscription` | 權威唯一性：此表重複承載 'customer' 的權威屬性 ['customer_email']（權威表：dim_customer）。應引用而非複製。 <br>**期望** 'customer' 的屬性只在權威表 dim_customer 落地 ｜ **實際** subscription 重複承載 ['customer_email'] <br>**修法** 移除 ['customer_email']，改以 customer_id 關聯 dim_customer <br>_理由：同一實體兩個擁有者破壞單一真實源。_ | skill |
| ❌ | 閘門 | `SKILL.ssot_join_keys` | `customer_id` | Join key 型別一致：'customer_id' 跨表型別不一致 [('dim_customer', 'int'), ('subscription', 'string'), ('billing_event', 'int')]。 <br>**期望** 'customer_id' 在所有表同一 base type ｜ **實際** dim_customer:int；subscription:string；billing_event:int <br>**修法** 統一型別（建議與權威表一致） <br>_理由：型別不符的跨域 join 不安全。_ | skill |
| ⚠️ | 閘門 | `SKILL.ssot_authority` | `dim_product` | 權威表在場檢視：'product' 的權威表不在本次 DDL。 <br>_理由：若它屬於另一 domain 的 schema 則屬正常。_ | skill |
| ⚠️ | 閘門 | `SKILL.ssot_fact_duplication` | `customer_email` | 事實重複：'customer_email' 出現在 ['dim_customer', 'subscription']；宣告擁有者為 'dim_customer'，其餘表應由它同步衍生。 <br>_理由：重複事實會漂移失同步。_ | skill |
| ⚠️ | 閘門 | `SKILL.ssot_join_keys` | `customer_id` | Join key 值編碼：'customer_id' 樣本值形態不一 {'dim_customer': 'int', 'subscription': 'digits_len7_zeropad', 'billing_event': 'int'}。 <br>_理由：編碼不一（如補零與否）會讓 join 對不上。_ | skill |
| ⚠️ | 閘門 | `SKILL.ssot_pii_amount_split` | `subscription` | 個資與金額應分表存放：欄位 'customer_email' 與 'MonthlyPrice' 不應同時存在 <br>**期望** customer_email、MonthlyPrice 擇一或分表 ｜ **實際** 兩者並存 <br>**修法** 將其中一者移至其權威表，以鍵引用 <br>_理由：PII 與金額混存使權限難分級、真實源歸屬模糊。_ | skill |
| ⚠️ | 閘門 | `SSOT.UNREGISTERED_SUBJECT` | `billing_event` | 未登錄主體候選 'event'：此表看似其權威表（證據欄位 ['amount', 'occurred_at']），但 SSOT registry 尚未登錄。建議先登錄再上線。 <br>**期望** 'event' 已登錄於 ssot.registry ｜ **實際** registry 查無此主體 <br>**修法** 於 config/default.yaml 的 ssot.registry 登錄 'event'（權威表 billing_event） <br>_理由：新 data subject 應先登錄權威表，否則跨域 SSOT 硬檢查無法涵蓋它。可由顧問區產 registry 草稿、人工確認後寫回。_ | rule |
| ⚠️ | 閘門 | `SSOT.UNREGISTERED_SUBJECT` | `subscription` | 未登錄主體候選 'subscription'：此表看似其權威表（證據欄位 ['customer_email', 'MonthlyPrice', 'started_at']），但 SSOT registry 尚未登錄。建議先登錄再上線。 <br>**期望** 'subscription' 已登錄於 ssot.registry ｜ **實際** registry 查無此主體 <br>**修法** 於 config/default.yaml 的 ssot.registry 登錄 'subscription'（權威表 subscription） <br>_理由：新 data subject 應先登錄權威表，否則跨域 SSOT 硬檢查無法涵蓋它。可由顧問區產 registry 草稿、人工確認後寫回。_ | rule |
| ⏭️ | 顧問 | `SKILL.ssot_semantic` | `(skill)` | 未接 LLM，略過語意卡控「SSOT 候選衝突偵測（語意）」。 | llm |
| ⏭️ | 閘門 | `PRODUCTION.SCOPE` | `(production)` | 未明確指定業務 domain，不參照 production 基準區。 | rule |
| ✅ | 閘門 | `SKILL.ssot_pii_amount_split` | `2 表` | 個資與金額應分表存放：2 表全數通過（dim_customer、billing_event） <br>_理由：PII 與金額混存使權限難分級、真實源歸屬模糊。_ | skill |

## 資料設計概念（主體性）

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ⏭️ | 顧問 | `CONCEPT.SUBJECT` | `(schema)` | 未設定 LLM，略過主體性概念層。 | llm |

## Lineage 關聯治理

| | 區 | 檢查 | 對象 | 說明 | 來源 |
|---|---|---|---|---|---|
| ❌ | 閘門 | `LINEAGE.TYPE_COMPATIBILITY` | `local.dim_customer.customer_id → subscription.customer_id` | lineage 來源與目標欄位型別不相容。 <br>**期望** 目標基本型別 int ｜ **實際** 目標基本型別 string <br>**修法** 調整目標型別或改正 lineage 欄位映射。 | rule |
| ℹ️ | 顧問 | `PRODGRAPH.IMPACT` | `dim_customer` | 正式區有 1 處依賴此表：CRM/order（orders.customer_id）。此表的結構或語意變更會影響這些 subject。 <br>**修法** 變更前通知依賴方；破壞性變更應開新表版本而非原地修改。 | rule |
| ✅ | 閘門 | `LINEAGE.COLUMN_EXISTS` | `(lineage)` | 所有 lineage 欄位映射都可解析。 | rule |
| ✅ | 閘門 | `LINEAGE.CYCLE` | `(lineage)` | local lineage 未形成循環。 | rule |
| ✅ | 閘門 | `LINEAGE.DOMAIN_SCOPE` | `(lineage)` | 所有外部上游 domain 都已明確選取。 | rule |
| ✅ | 閘門 | `LINEAGE.METADATA` | `(lineage)` | case config 的 lineage 格式與目標表有效。 | rule |
| ✅ | 閘門 | `LINEAGE.UPSTREAM_EXISTS` | `(lineage)` | 所有宣告的上游資料表都存在。 | rule |
| ✅ | 閘門 | `PRODGRAPH.CARDINALITY_CONFLICT` | `(全域關聯圖)` | 關聯宣告與正式區既有 subject 的基數一致。 | rule |
| ✅ | 閘門 | `PRODGRAPH.CYCLE` | `(全域關聯圖)` | 加入本 subject 後全域關聯圖無循環。 | rule |
