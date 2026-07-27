# 與 frank0124p/dataval 同步紀錄

> 對應合併提交 `e01a778`（`Merge frank0124p/dataval …`）。原則：**衝突以 frank 為主，
> 儘量保留我加的功能，最後讓整份專案正常運作**。

## 背景

我的分支 `improve/skill-ci-lineage-frontend` 與 `frank/main` 共用基底 `cf970bd`，各自
往前長：

- **我這邊（3 個提交）**：CI／lineage 修復 ＋ ingest skill ＋ 本機 webapp ＋ 前端七分頁
  ＋ 六支工具（scaffold_input／report_diff／simulate_impact／report_paths／…）。
- **frank 那邊（4 個提交）**：治理生命週期強化、驗證 bundle（provenance）、樣本改為
  選填、顧問區補完納入標準報告流程、報告新增「規則涵蓋清單」、prodgraph 端點改用
  domain 限定 key。

兩邊都動到 `run.py`／`report.py`／`prodgraph.py`／`precheck.py`／`merge_advisory.py`／
`promote.py`／`rules.py`／`tests/*` 等，必然衝突。

## 合併策略

用 `git merge -X theirs frank/main`：**衝突的段落取 frank 的**，兩邊不衝突的變更都保留，
所以我新增的獨立檔案（webapp.py、frontend/、graph_export.py…）原封保留，而共享檔案的
衝突段落一律以 frank 為準。合併後再逐一修復「-X theirs 把我的用法留下、卻把對應定義／
import 換成 frank 版」造成的破綻。

## frank 為主（衝突取他）

- 治理／provenance／樣本選填／顧問區流程／規則涵蓋清單等核心邏輯。
- `merge_advisory.py`、`promote.py`、`lineage.py`：整檔取 frank 版（我的改動在扁平佈局下
  已無必要）。
- `tests/golden/subscription.json`：取 frank 的黃金基準。
- `prodgraph.py`：還原成與 frank 逐位元組相同（見下）。

## 保留我的功能

- webapp.py 與 frontend/index.html 的七個分頁、scaffold_input.py、report_diff.py、
  simulate_impact.py、report_paths.py、ingest-reference skill 全數保留可用。
- `dataval/report.py::diff_findings`、`rules.py new-domain` 保留。

## 為了同時運作做的修復

1. **報告佈局回到 frank 的扁平 `reports/`**（唯一真正被放棄的我方功能：domain 分類
   `reports/<域>/`）。frank 的流程與測試假設扁平；我的 `find_report_json` 對扁平仍可運作，
   所以工具不受影響。`.gitignore` 也改回扁平 glob ＋ 保留 `reports/.history/`。
2. **補回被 -X theirs 拆散的定義**：`rules.py` 的 `cmd_new_domain`／`_write_if_absent`
   （派工行留著但定義被換掉，會 NameError）；`run.py`／`promote.py` 掉的 `report_paths`
   import。
3. **把 `export_graph` 從 prodgraph.py 移到新檔 `dataval/graph_export.py`**：frank 的
   provenance 會逐檔雜湊 validator 來源，動 prodgraph.py 會讓驗證 bundle 版本碼一直變。
   移出後 prodgraph.py 與 frank 完全一致；export_graph 也改用 frank 的 domain 限定
   `_edges(relations, owner_domain)`，節點 id 變成 `<domain>.<table>`。
4. **黃金基準修正**：T1 失敗其實是我 fixture 裡多留了一行 `PRODGRAPH.IMPACT`——frank 的
   程式對 subscription 本來就不會產生它（已用 worktree 對照確認），故取 frank 的 fixture。
5. webapp 送驗改為寫扁平報告；docstring／README 的分類字樣一併更正為扁平。

## 驗證

- `python -m unittest discover -s tests -p "*_test.py"` → **90 passed**（含 frank 新增的
  advisory_merge_test／rule_safety_test 與我的 tooling_test）。
- `python tests/golden_test.py` → 全過；`python rules.py lint` → 乾淨。
- CLI（run.py／promote.py／rules.py new-domain）與 webapp（全部路由、POST /api/validate、
  /api/lineage-graph）都實測可用，server log 乾淨。

## 備註

- 本機留了安全標籤 `backup-before-frank-sync`（合併前的 HEAD）與 `frank` remote，方便回溯，
  不影響版控。
- 唯一放棄的我方功能是報告的 domain 分類；其餘皆保留。
