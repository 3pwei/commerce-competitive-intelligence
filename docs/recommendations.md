# AI Recommendations and Recent Suggestion

PR #9 consumes only `overall_trend.json`, `detected_events.json`, optional validated
`comment_evidence.json`, and product configuration. It never repeats collection, parsing,
review analysis, or deterministic business rules.

## Safety and traceability

- PR #8 events remain the source of truth for prices, stock, severity, and review findings.
- Because the PR #8 event contract predates an explicit ID field, the context builder assigns a
  stable `evt-<ordinal>-<sha256>` identity from the complete validated event payload. The sidecar
  stores that identity together with the unchanged source event.
- Each product receives at most one merged recommendation, and every recommendation cites at
  least one supplied event ID.
- Products without events produce no recommendation and are listed in the summary.
- Priority is validated against PR #8 severity (`critical` → `high`, `warning` → `medium`,
  otherwise `low`). Unsupported event IDs, products, priorities, and SEQN values are rejected.
- The selected Sheet vendor is the highest-severity evidence vendor, with stable retailer order
  used only to break ties. Vendor-less insufficient-data evidence falls back to Amazon solely to
  satisfy the unchanged three-column Sheet contract; the evidence sidecar remains authoritative.
- Suggestions are advisory. No price, notification, Sheet, or external system is modified.

## Provider boundary

The recommendation generator uses the same `LLMProvider` protocol introduced in PR #6. The mock
provider is deterministic, performs no network access, and uses a fixed metadata timestamp. The
configured provider obtains its endpoint, API key, provider name, and model only from environment
variables. Invalid structured output is retried once and then rejected.

## Outputs

The `recommendations` command writes:

- `recent_suggestion.json` and `recent_suggestion.csv`, matching the schema manifest exactly
- `recommendation_evidence.json`, containing cited event payloads and related comment evidence
- `recommendation_summary.json`, containing run counts and full structured recommendations
