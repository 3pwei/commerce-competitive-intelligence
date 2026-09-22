# Review collection and analysis

PR #6 adds an Amazon-only review boundary and structured, evidence-linked analysis. The
default command is fully offline:

```bash
python -m competitive_intelligence reviews --mode fixture --provider mock
```

Three sanitized, synthetic fixtures are replayed through `FixtureReviewSource`. Reviews are
normalized, sorted newest-first, deduplicated by review ID, and capped at 20 per product.
Empty text is discarded and each review body is capped at 2,000 characters. Total serialized
input is capped at 20,000 characters and each product is allowed at most two provider calls.

`LLMProvider` isolates the analysis workflow from any vendor. The deterministic mock provider
is used by CI. The generic configured adapter reads `LLM_API_URL`, `LLM_API_KEY`, `LLM_MODEL`,
and `LLM_PROVIDER` from the environment; credentials are never accepted in configuration
files. Its endpoint must accept JSON with `model`, `prompt`, and `response_format`, returning a
JSON object whose `output` field contains the structured analysis JSON.

Review text is serialized inside an explicit untrusted-data envelope. It is never executed and
instructions inside it must be ignored. Full product-page HTML is never sent to a provider.
Provider output is validated by Pydantic and against the actual normalized review IDs. Invalid
output is retried once and then fails explicitly. This PR does not write to the `Comment` Sheet.
