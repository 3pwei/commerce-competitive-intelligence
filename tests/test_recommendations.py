"""Evidence-bound recommendation and Recent Suggestion tests."""

import csv
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from competitive_intelligence.config import load_product_catalog
from competitive_intelligence.contracts import RecentSuggestionRow, sheet_headers
from competitive_intelligence.recommendations import (
    MockRecommendationProvider,
    RecommendationCategory,
    build_recommendation_contexts,
    build_recommendations,
    generate_recommendation,
    write_recommendation_outputs,
)
from competitive_intelligence.trends import DetectedEvent

ROOT = Path(__file__).parents[1]
CATALOG = load_product_catalog(ROOT / "config/products.example.json")


def event(product: int = 0, **changes: object) -> dict[str, object]:
    configured = CATALOG.products[product]
    payload: dict[str, object] = {
        "rule_id": "COMPETITOR_PRICE_LOWER",
        "product_id": configured.product_id,
        "product_name": configured.product_name,
        "vendor": "amazon",
        "severity": "warning",
        "seqn": "batch-1",
        "evidence": {"final_price": "199.00", "own_price": "249.00"},
    }
    payload.update(changes)
    return payload


def trend_rows() -> list[dict[str, str]]:
    return [
        {
            "Product Name": product.product_name,
            "Vendor": "amazon",
            "Overall Trend": "COMPETITOR_PRICE_LOWER",
            "Observation": "COMPETITOR_PRICE_LOWER",
        }
        for product in CATALOG.products
    ]


class Responses:
    provider_name = "test"
    model_name = "test-model"

    def __init__(self, values: list[str]) -> None:
        self.values = values
        self.calls = 0

    def complete(self, prompt: str) -> str:
        del prompt
        value = self.values[min(self.calls, len(self.values) - 1)]
        self.calls += 1
        return value


def test_three_products_generate_traceable_merged_recommendations() -> None:
    events = [event(index) for index in range(3)] + [event(0, vendor="walmart")]
    result = build_recommendations(trend_rows(), events, CATALOG, MockRecommendationProvider())
    assert len(result.recommendations) == len(result.rows) == 3
    assert len(result.evidence[0].event_ids) == 2
    assert result.recommendations[0].category is RecommendationCategory.PRICING_REVIEW
    assert all(item.event_ids for item in result.recommendations)
    assert {source.event_id for item in result.evidence for source in item.source_events} == {
        event_id for item in result.recommendations for event_id in item.event_ids
    }


def test_no_event_product_gets_no_fabricated_alert() -> None:
    result = build_recommendations(trend_rows(), [event()], CATALOG, MockRecommendationProvider())
    assert [item.product_id for item in result.recommendations] == [CATALOG.products[0].product_id]
    assert result.summary.products_without_events == [
        CATALOG.products[1].product_id,
        CATALOG.products[2].product_id,
    ]


def test_missing_event_invalid_priority_and_unsupported_claim_are_rejected() -> None:
    contexts, _, _ = build_recommendation_contexts(trend_rows(), [event()], CATALOG)
    event_id = contexts[0].events[0].event_id
    base = {
        "product_id": CATALOG.products[0].product_id,
        "event_ids": [event_id],
        "priority": "medium",
        "category": "pricing review",
        "recommended_action": "Review price.",
        "rationale": "Based on the event.",
        "evidence_summary": "One price event.",
        "limitations": "Human review required.",
    }
    missing = Responses([json.dumps(base | {"event_ids": ["missing"]})])
    with pytest.raises(ValueError, match="missing event"):
        generate_recommendation(contexts[0], missing)
    invalid_priority = Responses([json.dumps(base | {"priority": "urgent"})])
    with pytest.raises(ValueError, match="invalid recommendation"):
        generate_recommendation(contexts[0], invalid_priority)
    unsupported = Responses([json.dumps(base | {"category": "inventory response"})])
    with pytest.raises(ValueError, match="unsupported"):
        generate_recommendation(contexts[0], unsupported)
    assert missing.calls == invalid_priority.calls == unsupported.calls == 2


def test_malformed_response_retries_once_then_succeeds() -> None:
    contexts, _, _ = build_recommendation_contexts(trend_rows(), [event()], CATALOG)
    expected = MockRecommendationProvider().complete(
        __import__(
            "competitive_intelligence.recommendations", fromlist=["build_recommendation_prompt"]
        ).build_recommendation_prompt(contexts[0])
    )
    provider = Responses(["not-json", expected])
    assert (
        generate_recommendation(contexts[0], provider).product_id == CATALOG.products[0].product_id
    )
    assert provider.calls == 2


def test_seqn_identity_and_source_event_validation() -> None:
    with pytest.raises(ValueError, match="same SEQN"):
        build_recommendation_contexts(trend_rows(), [event(), event(1, seqn="batch-2")], CATALOG)
    bad = event(product_id="unknown")
    with pytest.raises(ValueError, match="unknown product"):
        build_recommendation_contexts(trend_rows(), [bad], CATALOG)
    with pytest.raises(ValidationError):
        DetectedEvent.model_validate(event(severity="urgent"))


def test_json_csv_contract_and_mock_are_deterministic(tmp_path: Path) -> None:
    first = build_recommendations(trend_rows(), [event()], CATALOG, MockRecommendationProvider())
    second = build_recommendations(trend_rows(), [event()], CATALOG, MockRecommendationProvider())
    assert first.model_dump_json() == second.model_dump_json()
    write_recommendation_outputs(first, tmp_path)
    json_rows = json.loads((tmp_path / "recent_suggestion.json").read_text(encoding="utf-8"))
    with (tmp_path / "recent_suggestion.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == sheet_headers(RecentSuggestionRow)
        assert list(reader) == json_rows
    assert list(json_rows[0]) == sheet_headers(RecentSuggestionRow)
    assert {path.name for path in tmp_path.iterdir()} == {
        "recent_suggestion.json",
        "recent_suggestion.csv",
        "recommendation_evidence.json",
        "recommendation_summary.json",
    }
