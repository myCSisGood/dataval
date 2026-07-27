# 輸入前置檢核 — subscription

**結果：✅ 通過**

一組 data subject 需要三件必備輸入（DDL／relations／context），樣本為選填（存在 → 可解析 → 一致，三層檢核）：

| 檢核項 | 狀態 | 說明 |
|---|---|---|
| DDL | ✅ | subscription.sql（3 張表：dim_customer、subscription、billing_event） |
| 樣本資料 | ✅ | samples/（billing_event 3 列、dim_customer 3 列、subscription 3 列） |
| 關聯 | ✅ | relations.yaml（2 條） |
| 語意描述 | ✅ | context.md（subject: 訂閱；段落：這個 data subject 是什麼、粒度（每張表一行代表什麼）、用途與消費者、上下游來源） |
