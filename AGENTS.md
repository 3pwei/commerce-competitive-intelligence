# Repository Instructions

## Scope discipline

- 每個 PR 只修改該 PR 明確指定的 scope；不要順帶實作後續功能。
- 維持展示型、人工觸發的架構，不加入資料庫、Redis、排程器或常駐服務。

## Test and data policy

- 優先以 `fixtures/` 中已清理的資料進行開發與測試。
- CI 不得呼叫真實網站、付費 API 或任何需要 credentials 的服務。
- 未清理的網頁內容與 Live Capture 只能放在被 Git 忽略的位置，不得提交。

## Integration boundaries

- 外部爬蟲、LLM、試算表與通知服務必須以 Python `Protocol`／Adapter 隔離，不得讓業務邏輯綁定特定供應商。
- Google Sheets 既有 schema 是後續資料契約；變更或實作前須依指定 PR scope 處理。
- n8n 負責人工觸發與流程編排，Python 負責可測試的核心處理邏輯。

## Security

- 禁止將 secrets、API keys、cookies、tokens、真實 credentials 或含敏感資訊的資料寫入 repository。
- 只提交安全的 `.env.example` 變數名稱與非敏感範例值。
- 新增整合時必須提供離線 fixture 測試，且測試預設不得連線至外部服務。

