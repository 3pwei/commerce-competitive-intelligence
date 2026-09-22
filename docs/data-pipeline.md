# STG / ODS / TGT data pipeline

The price and stock pipeline is an offline, deterministic transformation boundary. It reads the
committed fixture manifest through the existing replay/parser path and never constructs a live or
network-capable fetcher.

```text
Fixture replay -> parser observations -> STG -> ODS -> TGT
```

Run the JSON demo:

```bash
python -m competitive_intelligence pipeline --mode fixture --output-dir output/demo
```

Add `--format csv` for CSV stage outputs, or `--format both` for JSON and CSV. `rejected.json` and
`run_summary.json` are always JSON because they are pipeline audit artifacts rather than Sheet
tabs.

## Layer rules

- **STG** maps every parser observation to the exact eight STG contract headers. The execution
  creates one sortable `SEQN`, shared by every row in that batch. Incomplete observations remain
  visible and are rejected explicitly by ODS rather than disappearing.
- **ODS** validates the existing `PriceRow` contract, canonicalizes supported vendor aliases and
  product identity, preserves a missing `Base Price`, and rejects invalid prices, timestamps,
  stock values, unknown products, and exact duplicates. Every rejection includes its stage,
  reason, source identity, and original STG record.
- **TGT** consumes only accepted ODS rows, keeps one deterministic row for each product/vendor,
  joins `My price` from the product configuration, and sorts by product then vendor. It does not
  infer or replace retailer prices.

This PR has no historical store. For a single fixture batch, `Recent Stock` and `Current Stock`
therefore both carry the accepted ODS stock value. A future persistence/Sheets integration must
define cross-batch prior-state semantics before those values can diverge.

## Reconciliation and repeatability

`run_summary.json` records STG, accepted ODS, rejected ODS, and TGT counts. The invariant
`STG = ODS accepted + ODS rejected` makes every staged row accountable. Replaying the same fixture
with the same injected batch identifier produces identical business output; normal CLI runs use a
fresh sortable `SEQN` to identify the execution.

