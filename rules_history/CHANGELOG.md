# 規則版控（自動維護，最新在最上）

每次 `run.py` 偵測到規則集變更時自動寫入；完整快照見同名 `.json`。

## 2026-07-24T09:55:01+00:00 ｜ f70bd1adfb9f71ef → 6e29b1af52a1883f ｜ ➕0 ➖0 ✏️0 ｜ 共 39 條
- 🧩 驗證引擎／Python rule／依賴版本 bundle 有變更
- 快照：`20260724T095501Z_6e29b1af.json`

## 2026-07-22T14:45:42+00:00 ｜ e4233a9950048118 → f70bd1adfb9f71ef ｜ ➕0 ➖0 ✏️6 ｜ 共 39 條
- ✏️ 修改 `no_future_event_time`：source_sha256
- ✏️ 修改 `ssot_authority`：source_sha256
- ✏️ 修改 `ssot_fact_duplication`：source_sha256
- ✏️ 修改 `ssot_join_keys`：source_sha256
- ✏️ 修改 `structural_fk_resolves`：source_sha256
- ✏️ 修改 `structural_type_sample`：source_sha256
- 🧩 驗證引擎／Python rule／依賴版本 bundle 有變更
- 快照：`20260722T144542Z_f70bd1ad.json`

## 2026-07-22T12:26:41+00:00 ｜ 795825d8cfd76616 → e4233a9950048118 ｜ ➕1 ➖0 ✏️0 ｜ 共 39 條
- ➕ 新增 `scm_grn_needs_po`（SCM／gating／blocking）：收貨單必須掛採購單號
- 快照：`20260722T122641Z_e4233a99.json`

## 2026-07-22T11:37:36+00:00 ｜ 4ba014a26ccbf312 → 795825d8cfd76616 ｜ ➕0 ➖0 ✏️1 ｜ 共 38 條
- ✏️ 修改 `scm_po_needs_supplier`：enforcement
- 快照：`20260722T113736Z_795825d8.json`

## 2026-07-22T11:37:27+00:00 ｜ 295d3d51334af3df → 4ba014a26ccbf312 ｜ ➕1 ➖0 ✏️0 ｜ 共 38 條
- ➕ 新增 `scm_po_needs_supplier`（SCM／gating／blocking）：採購單必須掛供應商(範例)
- 快照：`20260722T113727Z_4ba014a2.json`

## 2026-07-22T11:37:27+00:00 ｜ （首版） → 295d3d51334af3df ｜ ➕37 ➖0 ✏️0 ｜ 共 37 條
- ➕ 新增 `best_practice_semantic`（Common／advisory／advisory）：依表型態的最佳實踐建議（語意）
- ➕ 新增 `blm_baseline`（BLM／gating／warning）：BLM 領域基線(範例佔位,請以實際 BLM 規範替換)
- ➕ 新增 `bp_datetime_timezone`（Common／gating／warning）：DateTime 應標明時區
- ➕ 新增 `bp_lowcardinality_status`（Common／gating／blocking）：status 欄位須用 LowCardinality（ClickHouse）
- ➕ 新增 `bp_money_decimal`（Common／gating／blocking）：金額欄位必須用 Decimal
- ➕ 新增 `bp_no_float`（Common／gating／blocking）：不可使用 Float 型別
- ➕ 新增 `fcm_baseline`（FCM／gating／warning）：FCM 領域基線(範例佔位,請以實際 FCM 規範替換)
- ➕ 新增 `fcm_master_data_semantic`（FCM／advisory／advisory）：FCM｜主檔語意一致性
- ➕ 新增 `naming_column_case`（Common／gating／blocking）：欄位名須為 snake_case 全小寫
- ➕ 新增 `naming_columns_commented`（Common／gating／blocking）：所有欄位必須有 COMMENT 註解
- ➕ 新增 `naming_glossary`（Common／gating／warning）：命名對照詞彙字典
- ➕ 新增 `naming_identifier_length`（Common／gating／warning）：識別字長度不超過 64 字元
- ➕ 新增 `naming_pk_suffix`（Common／gating／warning）：主鍵欄位建議以 _id 結尾
- ➕ 新增 `naming_reserved_words`（Common／gating／warning）：欄位名避免 SQL 保留字
- ➕ 新增 `naming_semantic`（Common／advisory／advisory）：跨表命名語意一致性（語意）
- ➕ 新增 `naming_table_snake_case`（Common／gating／blocking）：表名須為 snake_case 全小寫
- ➕ 新增 `no_future_event_time`（Common／gating／python）：Imperative skill: event_time-like columns should not allow obviously wrong
- ➕ 新增 `plm_bom_needs_quantity`（PLM／gating／blocking）：PLM｜BOM 必須記錄用量
- ➕ 新增 `plm_bom_structural_integrity`（PLM／advisory／advisory）：PLM｜BOM 結構完整性（語意）
- ➕ 新增 `plm_engineering_change`（PLM／advisory／advisory）：PLM｜工程變更管理（語意）
- ➕ 新增 `plm_lifecycle_stage`（PLM／advisory／advisory）：PLM｜生命週期階段（語意）
- ➕ 新增 `plm_part_master_baseline`（PLM／gating／blocking）：PLM｜料件主檔基線
- ➕ 新增 `plm_revision_versioning`（PLM／advisory／advisory）：PLM｜版次與版本控制（語意）
- ➕ 新增 `scm_supplier_baseline`（SCM／gating／blocking）：供應商主檔基線(範例,依實際 SCM 規範替換)
- ➕ 新增 `scm_supply_semantic`（SCM／advisory／advisory）：供應鏈語意檢視(範例,依實際 SCM know-how 替換)
- ➕ 新增 `ssot_authority`（Common／gating／python）：SSOT 權威唯一性（依 registry，跨表）— 由舊 SSOT.AUTHORITY_* 搬遷。
- ➕ 新增 `ssot_fact_duplication`（Common／gating／python）：同一事實不可散落多表（依 attribute_owner）— 由舊 SSOT.FACT_DUPLICATION 搬遷。
- ➕ 新增 `ssot_join_keys`（Common／gating／python）：跨表 join key 相容性（型別＋樣本編碼）— 由舊 SSOT.JOIN_KEY_* 搬遷。
- ➕ 新增 `ssot_pii_amount_split`（Common／gating／warning）：個資與金額應分表存放
- ➕ 新增 `ssot_semantic`（Common／advisory／advisory）：SSOT 候選衝突偵測（語意）
- ➕ 新增 `structural_audit_columns`（Common／gating／warning）：表應有稽核欄位（created_at / updated_at）
- ➕ 新增 `structural_business_key`（Common／gating／blocking）：表必須有 Business Key
- ➕ 新增 `structural_engine_mergetree`（Common／gating／blocking）：明細表引擎須為 MergeTree 系列（ClickHouse）
- ➕ 新增 `structural_fk_resolves`（Common／gating／python）：FK 目標必須存在（跨表）— 由舊 STRUCT.FK_RESOLVES 搬遷。
- ➕ 新增 `structural_key_not_nullable`（Common／gating／blocking）：鍵欄位不可為 Nullable
- ➕ 新增 `structural_order_by`（Common／gating／blocking）：表必須有 ORDER BY（ClickHouse）
- ➕ 新增 `structural_type_sample`（Common／gating／python）：宣告型別 vs 樣本資料一致（需樣本）— 由舊 STRUCT.TYPE_SAMPLE_MATCH 搬遷。
- 快照：`20260722T113727Z_295d3d51.json`

