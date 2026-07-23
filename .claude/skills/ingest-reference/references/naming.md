# reference：命名慣例 → `config/<域>/naming/glossary.yaml`

詞彙字典是 naming 卡控的依據(`require: no_banned_term` / `no_alias_term` /
`term_in_glossary` 會對照它)。按域合併:Common 為基底,各域可增補/覆蓋。

## Grammar(只有三個頂層 key)

```yaml
banned_terms:      # 禁用詞 → 建議改用的標準詞(欄位名含左邊的詞就報違規)
  cust: customer
  qty: quantity
aliases:           # 別名 → 正規詞(同義但非標準的寫法)
  buyer: customer
  sku: product
standard_terms: []  # 認可的標準詞白名單;留空 = 不啟用白名單,只用上面兩個黑名單
```

## 落地方式(重要:用 Edit,不要整檔覆蓋)

`config/<域>/naming/glossary.yaml` 多半已存在且**有檔頭註解**。用 Edit 工具在對應
key 底下插入新條目,保留原有註解與既有條目。**不要**用 `yaml.safe_dump` 整檔重寫
(會弄丟註解與排序)。只有該域完全沒有 glossary.yaml 時才整份新建。

跨域一致性:同一個詞在不同域若有衝突(例如 `item` 在 PLM 指料件、在別處指
product),放進**該域**的 glossary 覆蓋 Common,不要改 Common 基底。

## 自我驗證(必跑)

```bash
.venv/bin/python -c "
import yaml
d = yaml.safe_load(open('<path>')) or {}
assert set(d) <= {'banned_terms', 'aliases', 'standard_terms'}, list(d)
assert isinstance(d.get('banned_terms', {}), dict)
assert isinstance(d.get('aliases', {}), dict)
assert isinstance(d.get('standard_terms', []), list)
print('glossary ok:', {k: len(d.get(k) or []) for k in ('banned_terms','aliases','standard_terms')})
"
```

多出未知頂層 key、或 `banned_terms`/`aliases` 不是 mapping,引擎會把整份字典
當壞檔略過(並回報 warning),所以三個 key 的型別要正確。
