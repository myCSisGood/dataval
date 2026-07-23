# reference：E2E flow → `config/<域>/flows/<名>.flow.yaml`

描述資料從來源到消費端的有序站點。sequence diagram / 上下游文字描述都轉成這個
格式(見 `dataval/flows.py`)。

## Grammar

```yaml
flow: eco_to_bom              # 流程代號(英數底線)
title: 工程變更到 BOM 生效     # 顯示名稱
description: 一句話說明流程在做什麼
stages:                       # 依序的站點
  - name: 工程變更系統
    kind: source              # source | table | report,只能這三種
  - name: part_master         # kind=table 時 name 必須是實際表名
    kind: table
  - name: 生效版次報表
    kind: report
```

- `kind` 只能是 `source` / `table` / `report`(`dataval/flows.py` 的
  `VALID_KINDS`)。寫錯值會被判 `FLOW.SPEC` warning。
- `kind: table` 的站點,`name` 要對得上 DDL 裡的表名,引擎才能標 `FLOW.CONTEXT`
  (標出這張表在流程第幾站、上下游是誰)。
- 檔名建議 `<flow 代號>.flow.yaml`,副檔名必須是 `.flow.yaml` 或 `.flow.yml`。

## 落地

寫到 `config/<域>/flows/<flow 代號>.flow.yaml`。

## 自我驗證(必跑,不可有指向新檔的 FLOW.SPEC)

```bash
.venv/bin/python -c "
from dataval.flows import load_flows
flows, probs = load_flows('config', ['<域>'])
print('flows loaded:', [f.get('flow') for f in flows])
print('problems:', [p.message for p in probs])
"
```

`problems` 若出現指向你新檔的 `FLOW.SPEC`,代表格式錯(常見:`stages` 不是清單、
某站缺 `name`、`kind` 值不合法)。修到沒有為止。
