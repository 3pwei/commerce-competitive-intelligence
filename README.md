# Commerce Competitive Intelligence

競品價格與評論分析的展示型專案，作為後續 Python 分析元件、可替換的外部服務 Adapter，以及 n8n 人工流程的共同工程基礎。

## 專案定位

- 這是 side-project Demo，不是正式資料平台或常駐服務。
- n8n workflow 僅由使用者人工觸發，不建立自動排程。
- 專案不使用 PostgreSQL、SQLite、Redis 或其他資料庫。
- 預設 Demo 完全離線；只有人工關閉 dry run 並明確啟用整合時才呼叫外部服務。

## Python 與 n8n 的責任邊界

Python 負責可測試的資料擷取介面、解析、正規化與分析邏輯；外部服務以 `Protocol`／Adapter 隔離，避免綁定單一爬蟲或 LLM 供應商。n8n 負責人工啟動、步驟編排、輸入輸出傳遞，以及未來的 Google Sheets 與 Email 串接，不承載核心分析規則。

## Fixture 與 Live Capture 模式

一般開發、測試與 CI 預設使用 `fixtures/` 中已清理且可公開的範例資料。9 組商品頁 fixture 均明確標示為 synthetic，不能解讀為真實市場價格。一次性 Live Capture 必須由人工明確啟動並寫入被忽略的 `fixtures/live/`；資料經清理、去除敏感內容並完成審查後，才能成為版本控制內的 fixture。CI 永遠不執行 Live Capture。操作與安全規則見 [`docs/capture-and-replay.md`](docs/capture-and-replay.md)。

```bash
# 預設：完全離線 fixture replay
python -m competitive_intelligence capture

# 明確 opt-in：一次性 live capture
python -m competitive_intelligence capture --mode live
```

## 本機環境

需要 Python 3.12：

```bash
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
python -m competitive_intelligence --help
```

執行與 CI 相同的檢查：

```bash
ruff check .
ruff format --check .
mypy src
pytest
```

## 目錄

```text
config/                         Demo 設定範例
docs/                           設計與使用文件
fixtures/                       已清理的測試資料
n8n/workflows/                  後續可匯入的 workflow JSON
src/competitive_intelligence/   Python package
tests/                          自動測試
```

## 資料契約與產品設定

現有 Google Sheet 的六張工作表已定義為版本化、大小寫敏感的資料契約；三項 Demo 產品的價格與 retailer URL 則集中於非敏感設定檔。詳見 [`docs/data-contracts.md`](docs/data-contracts.md)。此階段只載入與驗證本機設定，不連線或寫入 Google Sheets。

## 網頁擷取與解析邊界

`PageFetcher` 將 direct HTTP、未來 browser／scraping API 與離線 fixture 隔離；Amazon、Walmart、Best Buy parser 只處理傳入的 HTML，依 JSON-LD、meta、retailer DOM 的順序抽取證據，不執行 JavaScript，也不猜測缺失的價格或庫存。CI 僅使用最小 synthetic HTML。

## STG / ODS / TGT 離線管線

Fixture replay 可直接轉換為符合既有 Sheet schema 的 STG、ODS 與 TGT JSON/CSV 檔案；
流程會驗證、正規化、去除完全重複資料並保留 rejected audit，不連線 Google Sheets：

```bash
python -m competitive_intelligence pipeline --mode fixture --output-dir output/demo
```

完整規則與對帳方式見 [`docs/data-pipeline.md`](docs/data-pipeline.md)。

## 評論分析

```bash
python -m competitive_intelligence reviews --mode fixture --provider mock
```

The default review flow replays sanitized Amazon fixtures and uses a deterministic mock
provider. See `docs/review-analysis.md` for provider configuration and safety limits.

## Comment Sheet 離線輸出

```bash
python -m competitive_intelligence comment-output \
  --mode fixture --provider mock --output-dir output/demo
```

此命令產生嚴格符合既有 `Comment` schema 的 JSON/CSV，以及獨立的 evidence 與
summary sidecar；不連線或修改 Google Sheets。完整欄位映射與 SEQN 傳遞方式見
[`docs/comment-output.md`](docs/comment-output.md)。

## Overall Trend 確定性規則

```bash
python -m competitive_intelligence overall-trend \
  --tgt output/demo/tgt.json \
  --comment output/demo/comment.json \
  --output-dir output/demo
```

此命令以價格、庫存及已驗證的 Comment evidence 執行確定性規則，產生符合
`Overall Trend` schema 的 JSON/CSV 與事件 sidecar；不呼叫 scraper、LLM 或 Google Sheets。
規則與追溯欄位見 [`docs/business-rules.md`](docs/business-rules.md)。

## AI 營運建議

```bash
python -m competitive_intelligence recommendations \
  --trend output/demo/overall_trend.json \
  --events output/demo/detected_events.json \
  --provider mock \
  --output-dir output/demo
```

此命令只根據 PR #8 已確認的事件產生人工作業建議，輸出符合 `Recent Suggestion`
schema 的 JSON/CSV 及 evidence/summary sidecar。Mock 模式完全離線且可重現；任何建議
都不會直接調價、通知或修改外部系統。詳見 [`docs/recommendations.md`](docs/recommendations.md)。

## n8n 端到端 Demo

```bash
python -m competitive_intelligence demo-run \
  --mode fixture --provider mock --output-dir output/demo
```

命令會產生單一 `demo_bundle.json`，並在任何外部步驟前完成六張 Sheet contract 驗證與
Email preview。可匯入的人工 workflow、dry-run、SEQN 重複保護及 credentials 設定方式見
[`docs/n8n-integration.md`](docs/n8n-integration.md)。

## 尚未實作

部署、自動排程、Database、Dashboard 與常駐 API 不在此 Demo 範圍。
