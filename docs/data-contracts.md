# Data contracts

This PR treats the existing Google Sheet as an output contract. It defines validation and
configuration only; it does not connect to or write to Google Sheets.

## Versioned manifest

`config/sheet-schema.v1.json` is the source of truth for exact, case-sensitive worksheet and
column names. Version `1.0.0` mirrors the workbook observed for this PR:

| Worksheet | Exact columns |
| --- | --- |
| `STG` | `Item Number`, `Product Name`, `Vendor`, `Base Price`, `Final Price`, `Stock Status`, `Timestamp`, `SEQN` |
| `ODS` | `Item Number`, `Product Name`, `Vendor`, `Base Price`, `Final Price`, `Stock Status`, `Timestamp`, `SEQN` |
| `TGT` | `Item Number`, `Product Name`, `Vendor`, `Base Price`, `Final Price`, `My price`, `Recent Stock`, `Current Stock`, `Timestamp` |
| `Comment` | `Product Name`, `Vendor`, `Pros1`, `Pros2`, `Pros3`, `Cons1`, `Cons2`, `Cons3`, `Summary` |
| `Overall Trend` | `Product Name`, `Vendor`, `Overall Trend`, `Observation` |
| `Recent Suggestion` | `Product Name`, `Vendor`, `Suggestion` |

The names are preserved as-is, including `My price` and numbered `Pros` / `Cons` columns. Any
future rename, removal, or meaning change requires a new manifest version and matching model
change.

## Validation rules

- `Base Price` is nullable; price values that are present cannot be negative.
- `Final Price` and `My price` are required and cannot be negative.
- Stock fields accept only `In Stock` and `Out of Stock`.
- `Timestamp` must be ISO 8601, include `T`, and include a timezone (`Z` is accepted).
- `SEQN` is an opaque string identifying records from the same execution batch.
- Vendors normalize to `amazon`, `walmart`, or `bestbuy`; unrecognized vendors are rejected.
- Input records reject unknown columns and preserve exact Sheet header aliases.

## Product configuration

`config/products.example.json` contains the three non-sensitive Demo products. Prices and all
retailer URLs live in configuration rather than business logic. URLs are HTTPS and validated
against the expected Amazon, Walmart, and Best Buy hosts. The supplied links are retailer search
entry points so the Demo is not coupled to a transient listing identifier.

Load the catalog without network access:

```python
from pathlib import Path

from competitive_intelligence.config import load_product_catalog

catalog = load_product_catalog(Path("config/products.example.json"))
```

## Scope boundary

These contracts do not implement scraping, retailer parsing, fixture capture, LLM analysis, n8n
workflows, Google Sheets API access, or notifications. Tests read only committed JSON files and do
not call external services.
