# n8n workflows

`competitive-intelligence-demo.json` 是人工觸發的父 Workflow；
`competitive-intelligence-processing.json` 是實際執行各資料階段的子 Workflow。匯入時必須
先匯入 processing 與 `competitive-intelligence-sheets.json` 兩個子流程、再匯入父流程。
Sheets 子流程包含 SEQN 查重與六張 Sheet append。所有 Workflow 均不得內嵌 credentials。
設定與安全操作見 `docs/n8n-integration.md`。
