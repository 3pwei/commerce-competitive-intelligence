# System Architecture

## Complete architecture

```mermaid
flowchart TB
  U["Operator"] --> N["Manual n8n workflow"]
  U --> C["Python CLI"]
  N --> C
  C --> F["PageFetcher protocol"]
  F --> X["Fixture adapter"]
  F --> L["Direct HTTP / browser / scraping adapter"]
  X --> P["Retailer parser registry"]
  L --> P
  P --> S["STG / ODS / TGT pipeline"]
  R["Review source protocol"] --> A["Review analysis"]
  M["LLM provider protocol"] --> A
  S --> B["Deterministic business rules"]
  A --> B
  B --> Q["Recommendation provider"]
  S --> V["Six-sheet contract validation"]
  A --> V
  B --> V
  Q --> V
  V --> D["Demo bundle and evidence"]
  D --> G["Optional Google Sheets"]
  D --> E["Optional Gmail"]
```

All external calls sit behind a protocol or n8n credential boundary. Business rules and contract
validation remain in Python. The repository contains no credential, recipient, real Sheet ID, or
machine-specific path.

## Fixture and one-time live capture

```mermaid
flowchart LR
  A["Fixture mode default"] --> B["Sanitized manifest"] --> D["Parser"]
  C["Explicit live mode"] --> E["Fetcher adapter"] --> F["Ignored live directory"]
  F --> G["Sanitize and review"] --> H["Approved fixture"] --> D
  D --> I["Normalized observations"]
```

CI and the public Demo only use the upper fixture path. Live capture is a deliberate, one-time
operator action; its raw output is ignored by Git and cannot silently become a public fixture.

## Processing and delivery flow

```mermaid
flowchart TB
  A["Product observations"] --> B["STG"] --> C["ODS"] --> D["TGT"]
  E["Review fixtures"] --> F["LLM analysis"] --> G["Comment"]
  D --> H["Business rules"]
  G --> H
  H --> I["Overall Trend and events"]
  I --> J["Evidence-bound recommendations"] --> K["Recent Suggestion"]
  B --> L["Bundle validation"]
  C --> L
  D --> L
  G --> L
  I --> L
  K --> L
  L --> M["Dry-run artifacts"]
  L --> N["Optional Sheets append"]
  L --> O["Optional Email send"]
```

## Replaceable boundaries

| Boundary | Offline default | Optional implementation | Core guarantee |
|---|---|---|---|
| Product pages | Fixture fetcher | HTTP, browser, scraping API | Common observation model |
| Reviews | Fixture source | Provider-specific source | Normalized, deduplicated reviews |
| LLM | Deterministic mock | Configured HTTP provider | Structured output validation |
| Sheets | Local JSON/CSV | Google Sheets nodes in n8n | Exact six-sheet contracts |
| Email | HTML/text preview | Gmail node in n8n | Same validated bundle |

There is no scheduler, database, queue, dashboard, or resident API in v1.0.0.
