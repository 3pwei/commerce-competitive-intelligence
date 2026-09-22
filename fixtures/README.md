# Fixtures

此目錄只接受已清理、可公開且適合離線測試的範例資料。未清理的 Live Capture 不得提交。
`product-pages/` contains nine minimal, sanitized, explicitly synthetic retailer
fixtures and a hash-verified manifest. Run them offline with:

```bash
python -m competitive_intelligence capture --mode fixture
```

`live/` is ignored. Never commit raw pages, cookies, tokens, credentials, or personal
data. See `docs/capture-and-replay.md` before promoting reviewed evidence.
`reviews/` contains sanitized, synthetic Amazon review fixtures for the three configured Demo
products. They contain no account data, cookies, reviewer names, or other personal information.
