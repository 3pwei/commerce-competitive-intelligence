"""Tests for review normalization, collection, and structured analysis."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from competitive_intelligence.config import load_product_catalog
from competitive_intelligence.reviews import (
    FixtureReviewSource,
    MockLLMProvider,
    NegativeTrend,
    Review,
    analyze_product,
    normalize_reviews,
    run_review_analysis,
)

ROOT = Path(__file__).parents[1]


def review(review_id: str, text: str = "Useful product", rating: float = 4) -> Review:
    return Review(
        review_id=review_id,
        product_id="demo-product",
        rating=rating,
        title="Title",
        review_text=text,
        review_date=date(2026, 9, 1),
        captured_at=datetime(2026, 9, 2, tzinfo=UTC),
    )


def test_fixture_analysis_is_deterministic_and_evidence_linked() -> None:
    catalog = load_product_catalog(ROOT / "config/products.example.json")
    source = FixtureReviewSource(ROOT / "fixtures/reviews/manifest.json")
    first = run_review_analysis(catalog, source, MockLLMProvider())
    second = run_review_analysis(catalog, source, MockLLMProvider())

    assert [item.model_dump_json() for item in first] == [item.model_dump_json() for item in second]
    assert len(first) == 3
    for analysis in first:
        assert analysis.analyzed_review_count == 6
        evidence = set(analysis.supporting_review_ids)
        for finding in (
            analysis.positive_themes + analysis.negative_themes + analysis.recurring_issues
        ):
            assert set(finding.supporting_review_ids) <= evidence


def test_normalization_removes_duplicate_and_empty_reviews() -> None:
    valid = review("same")
    duplicate = valid.model_copy(update={"review_text": "Older duplicate"})
    empty = valid.model_copy(update={"review_id": "empty", "review_text": "   "})

    normalized = normalize_reviews([valid, duplicate, empty], "demo-product")

    assert [item.review_id for item in normalized] == ["same"]


def test_normalization_caps_input_at_twenty_reviews() -> None:
    reviews = [
        review(f"review-{index:02d}").model_copy(
            update={"review_date": date(2026, 9, (index % 28) + 1)}
        )
        for index in range(25)
    ]

    assert len(normalize_reviews(reviews, "demo-product")) == 20


def test_insufficient_data_has_warning_and_no_trend_claim() -> None:
    result = analyze_product("demo-product", [review("one")], MockLLMProvider())

    assert result.warnings == ["insufficient-data"]
    assert result.negative_trend is NegativeTrend.INSUFFICIENT_EVIDENCE


class MalformedProvider:
    provider_name = "broken"
    model_name = "broken-v1"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt: str) -> str:
        self.calls += 1
        return "not-json"


def test_malformed_provider_response_retries_once_then_fails() -> None:
    provider = MalformedProvider()

    with pytest.raises(ValueError, match="after 2 attempts"):
        analyze_product("demo-product", [review("one")], provider)

    assert provider.calls == 2


class UnknownEvidenceProvider:
    provider_name = "broken"
    model_name = "broken-v1"

    def complete(self, prompt: str) -> str:
        return """{
          "product_id":"demo-product",
          "positive_themes":[{"theme":"Good","supporting_review_ids":["unknown"]}],
          "negative_themes":[],"recurring_issues":[],
          "negative_trend":"insufficient_evidence","summary":"Summary",
          "analyzed_review_count":1,"supporting_review_ids":["unknown"],
          "warnings":["insufficient-data"]
        }"""


def test_unknown_supporting_review_id_is_rejected() -> None:
    with pytest.raises(ValueError, match="after 2 attempts"):
        analyze_product("demo-product", [review("one")], UnknownEvidenceProvider())
