# reference：規則描述 → `rules.py draft`(絕不直接寫 knowhow)

best practice、命名規則、結構要求等**會影響合規判定**的內容,不可直接寫進
`config/<域>/knowhow/`。這是專案鐵則:LLM 只能在**撰寫時**起草,人審＋lint 通過
才能 adopt;進了 knowhow 之後的執行永遠是確定性的。

## 判斷 gating 還是 advisory(先決定,見 `SKILL_AUTHORING.md` 第 0、2 節)

- 能機械判斷(有沒有某欄位、型別對不對、命名符不符)→ **gating**,用
  ` ```check `,`enforcement: blocking|warning`,**會擋**。
- 需要語意理解(主體抓對沒、語意一致沒)→ **advisory**,用 ` ```check-llm `,
  `enforcement: advisory`,**只提示**。
- category 擇一:`structural` / `naming` / `best_practice` / `ssot`。

## 流程

```bash
.venv/bin/python rules.py draft <域> <gating|advisory> <rule_id> "<自然語言需求>"
```

- 未接本地 LLM 時會產出 `drafts/<rule_id>.prompt.md`。依該檔裡的 **system 指引**
  產出 `drafts/<rule_id>.md`(只含規則內容本身,不要前後說明、不要 ``` 包裹)。
- gating 的 ` ```check ` 區塊**只能用 `SKILL_AUTHORING.md` 第 3 節列出的動詞**
  (has_column、column_type、not_nullable、has_business_key、datetime_with_timezone
  …等);表達不了就不要硬湊,在檔尾加 `<!-- NEEDS_PY: 原因 -->`,改寫成
  `config/Common/knowhow_py/` 的程式式規則。

## 交還給人(不可跳過)

產出草稿後**必須**明確告訴使用者:

> 這是草稿,尚未生效。請人工 review `drafts/<rule_id>.md`,確認後執行
> `.venv/bin/python rules.py adopt <rule_id>`(lint 通過才會搬進 knowhow)。

**agent 不得自己執行 `adopt`。** adopt 會 lint、通過才進
`config/<域>/knowhow/<區>/`,並在 `rules_history/` 記一筆生效。

## 自我驗證

```bash
.venv/bin/python rules.py check     # lint 所有規則檔與草稿格式
```
