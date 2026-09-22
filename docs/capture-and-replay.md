# One-Time Capture and Fixture Replay

The committed Demo path is offline and deterministic:

```bash
python -m competitive_intelligence capture
python -m competitive_intelligence capture --mode fixture
```

Both commands load `fixtures/product-pages/manifest.json`, verify each SHA-256 hash,
parse all nine sanitized evidence files, compare them with the recorded normalized
outputs, and validate conversion to the PR #2 price contract. Replay constructs no
network fetcher and makes no network request.

All nine committed fixtures are explicitly marked `synthetic`. They are minimal
parser evidence for three configured products across Amazon, Walmart, and Best Buy;
they are not represented as observed retailer prices.

## Explicit live capture

Live access is opt-in only:

```bash
python -m competitive_intelligence capture --mode live
```

The command processes each listing independently with a 10-second timeout, a
750,000-byte response cap, and one retry per method. Its provider-neutral chain is
direct HTTP, browser adapter, then scraping API adapter. The latter two are explicit
unconfigured boundaries until a free or user-supplied adapter is injected; no paid
service is activated. Failures are written to ignored
`fixtures/live/capture-failures.json` with attempted methods and typed reasons, and
the command returns non-zero if any listing failed.

Successful raw responses are never committed. Before writing to the ignored live
directory, the capture removes scripts (except JSON-LD evidence), styles, forms,
iframes, media, tracking attributes, and unrelated attributes. A human must review
sanitized evidence and create accurate manifest metadata before promoting it into
the committed fixture set.
