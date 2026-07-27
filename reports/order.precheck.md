# 輸入前置檢核 — order

**結果：✅ 通過**

一組 data subject 需要三件必備輸入（DDL／relations／context），樣本為選填（存在 → 可解析 → 一致，三層檢核）：

| 檢核項 | 狀態 | 說明 |
|---|---|---|
| DDL | ✅ | order.sql（2 張表：orders、order_items） |
| 樣本資料 | ✅ | samples/（order_items 10 列、orders 8 列） |
| 關聯 | ✅ | relations.yaml（2 條） |
| 語意描述 | ✅ | context.md（subject: 訂單；段落：這個 data subject 是什麼、粒度（每張表一行代表什麼）、用途與消費者、上下游來源） |
