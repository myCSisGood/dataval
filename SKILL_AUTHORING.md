# 如何產生一條 skill（給人與 agent 的生成指南）

這份文件是「**產生 skill 的 skill**」。它同時是：
- 給**人**的範本與步驟，照著就能寫出合格的 skill。
- 給 **opencode agent** 的生成規格——使用者描述一個治理需求，agent 讀這份指南，
  就能產出一個能被工具正確解析、且行為符合預期的 skill `.md`。

> 目標：讓更多人能貢獻 skill，把 data governance 的循環擴大——
> 每條沉澱下來的 know-how 都讓閘門更完整、顧問更聰明。

---

## 0. 先決定三件事

產任何 skill 前，先回答：

1. **這條在治理什麼？** 用一句話講清楚意圖（之後寫進「目的」段）。
2. **它能機械判斷，還是需要語意理解？**
   - 能用「有沒有某欄位／型別對不對／命名符不符」這種規則判斷 → **gating（確定性）**，用 ` ```check ` 卡控，**會擋**。
   - 需要「理解這個設計的意義」才能判斷（主體抓對沒、命名語意一致沒）→ **advisory（語意）**，用 ` ```check-llm ` 卡控，**只提示**。
   - 兩種都寫不出來、邏輯太複雜 → 改寫 Python skill（見第 6 節）。
3. **屬於哪一類、哪個 domain？**
   - 類別 category：`structural` / `naming` / `best_practice` / `ssot`（擇一）。
   - domain：放 `config/<domain>/knowhow/gating/` 或 `knowhow/advisory/`。
     跨 domain 共用的底線放 `Common/`。

---

## 1. skill 檔的固定結構

每條 skill 是一份 Markdown 規範文件，結構固定為「**檔頭 + 人讀規範 + 卡控區塊**」：

```markdown
---
id: <英數底線的唯一代號>
category: structural | naming | best_practice | ssot
enforcement: blocking | warning | advisory
---

# <規範標題>

## 目的
<這條在治理什麼、為何重要。會被帶進報告當理由。>

## 適用情境
<什麼樣的表/欄位適用。>

## 違反後果
<違反了會造成什麼問題，順帶說明為何設成這個 enforcement 等級。>

## 修正建議        ←（選填）違反時怎麼修；留空由卡控動詞自動生成

## 卡控
<這裡放 ```check 或 ```check-llm 區塊——見第 3、4 節>
```

**檔頭三個欄位的規則：**
- `id`：全專案唯一，建議用小寫英數與底線，例如 `txn_amount_needs_currency`。
- `category`：只能是那四個值之一。寫錯工具會拒絕載入。
- `enforcement`：
  - `blocking` → 進閘門區，違反會讓整體**判定不合規**（會擋）。
  - `warning` → 進閘門區，違反只**警告**、不擋。
  - `advisory` → 進顧問區，**只提示**。語意卡控（```check-llm）要用這個。

---

## 2. 兩種卡控的選擇（最關鍵的決定）

| | gating 確定性 | advisory 語意 |
|---|---|---|
| 卡控區塊 | ` ```check ` | ` ```check-llm ` |
| enforcement | blocking 或 warning | advisory |
| 會不會擋 | 會（blocking 時） | 永不擋 |
| 可重複 | 是（同輸入下每條 checking rule ID 結果相同） | 否（LLM 每次可能不同） |
| 何時用 | 規則能機械判斷 | 需要理解才能判斷 |
| 沒接 LLM 時 | 照常執行 | 自動略過 |

**鐵則：任何需要 LLM 判斷的東西，一律是 advisory、永不進入合規判定。**
不要試圖把語意判斷寫成 blocking——那會破壞「閘門區每次一致」的保證。

---

## 3. 產生 gating skill（```check）

正文最後放一個 ` ```check ` 區塊，每行一條卡控語句。**只能使用下列動詞**
（這是工具實際支援的全集；用了清單外的寫法，那一行會被當成無法解析而略過）。

### 限定適用範圍（選填，每條 skill 最多各一）
```
applies_to: name_matches "<正則>"      # 只對表名符合的表生效
applies_to: has_column <欄位名>         # 只對含此欄位的表生效
```

### 卡控條件（require，可多條）
```
require: has_column <欄位>                       # 必須有此欄位
require: column_type <欄位> <型別>                # 型別需為 int/decimal/datetime/string/float/bool/date/array/map
require: not_nullable <欄位>                      # 欄位不可為 Nullable
require: columns_not_both <A> <B>                # A、B 不可同時存在
require: name_matches <欄位> <正則>               # 欄位名稱需符合樣式
require: column_commented <欄位>                  # 該欄位必須有 COMMENT
require: all_columns_commented                   # 所有欄位都要有 COMMENT
require: has_business_key                        # 表必須有業務識別鍵
require: has_primary_key                         # 必須明確宣告 PRIMARY KEY（不把 ORDER BY 當 PK）
require: has_order_by                            # （ClickHouse）必須有物理排序鍵 ORDER BY
require: no_nullable_in_key                      # business / primary / sorting key 欄位不可 Nullable
require: engine_matches <正則>                    # （ClickHouse）引擎需符合，如 MergeTree
require: table_name_matches <正則>                # 表名需符合樣式
require: type_not_used <型別片段>                 # 不可使用某型別，如 Float
require: lowcardinality_when_present <欄位>        # （ClickHouse）該欄位存在時建議用 LowCardinality
require: no_banned_term                          # 欄位名不可含字典裡的禁用詞（對照 config/Common/naming/glossary.yaml）
require: no_alias_term                           # 欄位名不可用別名（非標準詞）
require: term_in_glossary                        # 欄位用詞須在認可字典內（需 glossary 設 standard_terms）
require: all_columns_name_match <正則>            # 所有欄位名須符合樣式
require: type_not_for_matching <欄名正則> <型別>   # 名稱符合者不可用該型別（金額禁 float）
require: datetime_with_timezone                  # DateTime 須標明時區
require: identifier_max_length <n>               # 表名/欄名長度上限
require: pk_ends_with <字尾>                      # 主鍵欄位須以某字尾結尾
require: columns_not_named <逗號清單>             # 欄位名避開保留字
```

### 完整範例（gating，blocking）
```markdown
---
id: txn_amount_needs_currency
category: best_practice
enforcement: blocking
---

# 交易金額必須記錄幣別

## 目的
交易表記錄金額卻未記錄幣別，金額將失去可解讀性，跨幣別情境無法換算對帳。

## 適用情境
交易相關表（transaction / billing / subscription）。

## 違反後果
金額語意不完整，下游彙總與換算會產生靜默錯誤。故設為會擋。

## 卡控
```check
applies_to: name_matches ".*(transaction|billing|subscription).*"
require: has_column currency
```
```

---

## 4. 產生 domain 語意層 skill（```check-llm）

當卡控需要理解設計的意義（規則寫不出來），正文最後放一個 ` ```check-llm ` 區塊，
裡面用**自然語言**描述要 LLM 判斷什麼。`enforcement` 必須是 `advisory`。

**寫 check-llm 的要點：**
- 用條列點出要檢查的面向，越具體越好。
- 要求 LLM 對每個發現指出「哪張表或哪個欄位」。
- 指定語氣為「**給設計者思考的提問**」，不要下結論（顧問區的定位）。
- 描述要綁定這個 domain 的概念（例如 PLM 就講 BOM、版次、生命週期）。

### 完整範例（domain 語意層，advisory）
```markdown
---
id: plm_bom_structural_integrity
category: ssot
enforcement: advisory
---

# PLM｜BOM 結構完整性（語意）

## 目的
BOM 的結構正確性無法只靠欄位規則判斷，需要理解父子關係、層級與用量的語意。

## 適用情境
承載 BOM、料件組成、產品結構的表。

## 違反後果
BOM 結構若有循環引用、缺漏父階、用量語意不清，會導致成本與需求展開錯誤。
需語意判斷，故只提示。

## 卡控
```check-llm
這是與 PLM 物料清單（BOM）相關的 schema。請從產品結構語意檢視：
- 是否清楚表達父件與子件的關係（assembly / component）？
- 是否有用量（quantity）欄位且語意明確（每單位父件所需子件數量）？
- 父子關係是否可能形成循環引用（A 含 B、B 又含 A）的風險？
- BOM 是否與版次／有效日期綁定，能表達不同版本的組成差異？
針對每個疑慮，指出相關的表或欄位，以「給設計者思考的提問」語氣描述。
```
```

---

## 5. 放置位置與命名

```
config/
├── Common/knowhow/{gating,advisory}/        ← 跨 domain 共用
└── <DOMAIN>/knowhow/{gating,advisory}/      ← 各領域，如 PLM、FCM
```

- gating skill（```check）放 `<domain>/knowhow/gating/`。
- advisory skill（```check-llm）放 `<domain>/knowhow/advisory/`。
- 檔名建議用 `id` 或可讀的描述，例如 `txn_amount_needs_currency.md`。
- 新增 domain 只要建資料夾、丟 `.md`，會自動被掃到，不用註冊。

---

## 6. 何時改用 Python skill

當判斷需要走訪整個 schema、跨表比對、遞迴（如真正偵測 BOM 循環引用），
` ```check ` 的語句寫不出來時，改寫 Python，放 `config/Common/knowhow_py/`：

```python
from dataval.model import Finding, ZONE_GATING
SKILL_META = {"id": "my_rule", "domain": "Common",
              "category": "ssot", "zone": ZONE_GATING,
              "empty_status": "pass"}
def check(schema, table):
    out = []
    # ...自訂邏輯，回傳 Finding 串列...
    return out
```

Python skill 必須宣告 `id` 與 `domain`。若函式沒有回傳 finding，
載入器會依 `empty_status`（預設 `pass`）產生明確結果；對「無可檢查對象」
的規則應設 `empty_status: skipped`。

---

## 7. 產出前的自我檢查清單（agent 必須逐項確認）

產出一個 skill `.md` 後，逐項核對：

- [ ] 檔頭有 `id`、`category`、`enforcement` 三欄，且值合法。
- [ ] category 是 structural / naming / best_practice / ssot 之一。
- [ ] 有 `# 標題`、`## 目的`、`## 適用情境`、`## 違反後果` 四段人讀規範。
- [ ] 有且只有一個卡控區塊（```check 或 ```check-llm）。
- [ ] gating（```check）→ enforcement 是 blocking 或 warning；
      advisory（```check-llm）→ enforcement 是 advisory。
- [ ] ```check 區塊內每一行都用第 3 節清單裡的動詞，沒有自由發明的語法。
- [ ] check-llm 的描述具體、要求指出表/欄位、語氣為提問。
- [ ] 放到正確的 `config/<domain>/knowhow/{gating,advisory}/` 目錄。
- [ ] 跑一次 `python run.py`，確認報告沒有「卡控語句無法解析」的警告，
      且這條 skill 出現在預期的區（閘門/顧問）。

---

## 8. 給 agent 的生成流程（一步步）

當使用者說「幫我新增一條 skill：<需求描述>」時：

1. 從需求判斷：能機械判斷嗎？→ 決定 gating 或 advisory（第 0、2 節）。
2. 決定 category 與 domain。
3. 套用第 1 節結構，填寫四段人讀規範。
4. 寫卡控區塊：
   - gating → 只用第 3 節清單的動詞組合卡控。
   - advisory → 用第 4 節要點寫自然語言描述。
5. 用空白範本 `config/_engine/templates/skill_gating.template.md` 或
   `config/_engine/templates/skill_advisory.template.md` 當骨架填。
6. 存到正確目錄、跑 `python rules.py check` 與 `python run.py`、核對第 7 節清單。
7. 把產出的 skill 路徑與「它會擋還是只提示、屬於哪一區」回報給使用者。
