---
name: ingest-reference
description: 把舊的/非結構化的資料治理參考資料(ERD 圖、flow 說明、命名慣例文件、
  best-practice 描述、截圖)轉換成本專案既有的結構化 config 檔案，或導向既有的
  rules.py draft/adopt 流程。使用時機：使用者提供一份舊文件/圖片/筆記，要求
  「整理進 config」「補齊 domain 資料」「這份資料怎麼用」。
---

# 引用轉換(ingest-reference)

把「舊的、非結構化的參考資料」轉成 dataval 既有的結構化格式。這**不是**
`SKILL_AUTHORING.md` 講的那種引擎執行的規則 `.md`;這是給人在對話裡呼叫的
操作指引。輸入可能是 `.sql`/`.md`/`.csv`/mermaid/yaml/sequence diagram,偶爾是
截圖——截圖就用 Read 工具讀圖後照同樣流程走。

## 流程(每次都照這四步)

1. **分類**:用下表判斷輸入屬於哪一類。混合多種內容就**拆開**,不要硬塞一類。
2. **讀對應的 reference 檔**:拿到該格式的完整 grammar、範例與驗證指令。
   (只讀你這次真正需要的那一個,不要全部讀。)
3. **落地**:照 reference 寫檔或呼叫既有 CLI。
4. **驗證＋總結**:跑 reference 裡的自我驗證指令,再依「輸出總結」回報。

## 分類決策表

| 輸入內容特徵 | 這一類是 | 讀哪個 reference |
|---|---|---|
| 表與表的關聯(有主體、有基數,如「一訂單對多明細」) | ERD | `references/erd.md` |
| 上下游站點順序 / sequence diagram(source→table→report) | E2E flow | `references/flows.md` |
| 詞彙、命名慣例(禁用詞、別名、標準詞) | naming 字典 | `references/naming.md` |
| best practice / 任何**會影響合規判定**的規則描述 | 規則(draft) | `references/rules.md` |
| 完整 DDL＋語意＋Sample＋ERD(新 data subject) | input 四件套 | 見 `input/README.md`,落地後跑 `run.py` |
| 「已進 BDP 正式區」的舊資料 | production | 不可直接寫,見下方「治理邊界」 |

## 治理邊界(任何一類都不可違反)

這三條是專案鐵則(見 `AGENTS.md`「不可破壞的保證」),skill 必須照做:

1. **規則不可直接寫進 `config/<域>/knowhow/`**。會影響 gating/advisory 判定的
   內容,一律走 `rules.py draft` → 人審 → `rules.py adopt`。skill 只能產草稿並
   提醒人審,**不得自己執行 `adopt`**。細節在 `references/rules.md`。
2. **`production/` 不可直接寫入或竄改**。正式區只能透過 `promote.py` 晉升,前提是
   該 subject 已通過 `run.py` 驗證。舊的「已進 BDP」資料應先整理成 `input/<名>/`
   四件套走驗證,不可捏造晉升記錄或直接複製檔案進 `production/`。
3. **ERD/flow/naming 是格式轉換,可直接寫檔**,但每次寫完都要在總結裡列出寫了
   什麼、讓人看過,不能默默寫完就結束。

## 輸出總結(每次跑完都要回報)

- 這份資料被判為哪一類、寫到/改到哪個檔案。
- reference 裡的自我驗證結果(通過或失敗訊息)。
- 若走 draft:明確提醒「這是草稿,需人工 review `drafts/<id>.md` 後才能
  `.venv/bin/python rules.py adopt <id>`」。
- 若有內容無法歸類:列出來、說明原因,交給使用者拆分,不要硬塞。
