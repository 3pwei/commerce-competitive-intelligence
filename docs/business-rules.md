# Business Rules and Overall Trend

`overall-trend` 讀取 PR #5 的 `tgt.json`、PR #7 的 `comment.json` 與同目錄 sidecar，
不重新擷取資料或呼叫 LLM。`Overall Trend` 欄位與順序完全由 schema manifest 決定；
rule ID、SEQN、severity 與 evidence 僅寫入 `detected_events.json`。

規則 severity 集中於 `config/business-rules.v1.json`。價格一律使用 `Decimal`，以
`Final Price` 由低至高排名並保留同價第一名；低於 own price 時，evidence 同時記錄
價差金額與百分比。沒有 `--previous-tgt` 時，summary 明確標示 `current_snapshot`，且
不產生庫存 change event。

輸入批次由 `tgt.json` 同目錄的 `run_summary.json`，以及 Comment 同目錄的
`comment_summary.json` 驗證。兩者 SEQN 不同時拒絕執行；Comment 或 evidence 檔案缺失
時仍會完成價格與庫存分析。輸出固定為：

- `overall_trend.json`
- `overall_trend.csv`
- `detected_events.json`
- `trend_summary.json`
