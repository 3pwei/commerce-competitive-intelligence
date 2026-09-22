"""File-backed stages used by the n8n sub-workflow."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from competitive_intelligence.capture import load_manifest, replay
from competitive_intelligence.comment_output import transform_comment_output, write_comment_outputs
from competitive_intelligence.config import ProductConfig, load_product_catalog
from competitive_intelligence.demo import (
    DemoBundle,
    DemoRunSummary,
    build_email,
    validate_bundle,
    write_demo_bundle,
)
from competitive_intelligence.parsing import ProductObservation
from competitive_intelligence.pipeline import run_pipeline, write_outputs
from competitive_intelligence.recommendations import (
    MockRecommendationProvider,
    StructuredRecommendation,
    build_recommendations,
    write_recommendation_outputs,
)
from competitive_intelligence.reviews import (
    ConfiguredLLMProvider,
    FixtureReviewSource,
    MockLLMProvider,
    Review,
    run_review_analysis,
)
from competitive_intelligence.trends import (
    analyze_trends,
    load_artifact_seqn,
    load_json_rows,
    load_rule_config,
    load_target_rows,
    write_trend_outputs,
)

ProviderName = Literal["mock", "configured"]


class CollectedReviewSource:
    """Read normalized reviews produced by the preceding n8n stage."""

    def __init__(self, path: Path) -> None:
        payload = _load_list(path)
        self._reviews: dict[str, list[Review]] = {}
        for item in payload:
            review = Review.model_validate(item)
            self._reviews.setdefault(review.product_id, []).append(review)

    def collect(self, product: ProductConfig) -> list[Review]:
        reviews = self._reviews.get(product.product_id)
        if not reviews:
            raise ValueError(f"Missing collected reviews for {product.product_id}")
        return list(reviews)


def run_n8n_stage(
    stage: str,
    output_dir: Path,
    *,
    provider: ProviderName = "mock",
    product_config: Path = Path("config/products.example.json"),
    product_fixtures: Path = Path("fixtures/product-pages/manifest.json"),
    review_fixtures: Path = Path("fixtures/reviews/manifest.json"),
    rules: Path = Path("config/business-rules.v1.json"),
    sheet_url: str = "",
) -> dict[str, object]:
    """Execute exactly one durable Demo stage and return its hand-off metadata."""
    stage_root = output_dir / "stages"
    paths = {
        "collection": stage_root / "product-pages",
        "parsed": stage_root / "parsed-products",
        "price": stage_root / "price-pipeline",
        "reviews": stage_root / "reviews",
        "trend": stage_root / "trend",
        "recommendations": stage_root / "recommendations",
    }
    catalog = load_product_catalog(product_config)

    if stage == "collect-product-pages":
        manifest = load_manifest(product_fixtures)
        destination = paths["collection"]
        destination.mkdir(parents=True, exist_ok=True)
        payload = {
            "mode": "fixture",
            "manifest": str(product_fixtures),
            "page_count": len(manifest.fixtures),
            "products": sorted({item.product_id for item in manifest.fixtures}),
            "vendors": sorted({item.vendor.value for item in manifest.fixtures}),
        }
        _write_json(destination / "collection_summary.json", payload)
        return payload

    if stage == "parse-retailer-html":
        _require(paths["collection"] / "collection_summary.json")
        observations = replay(product_fixtures)
        destination = paths["parsed"]
        destination.mkdir(parents=True, exist_ok=True)
        _write_json(
            destination / "product_observations.json",
            [item.model_dump(mode="json") for item in observations],
        )
        return {"observation_count": len(observations)}

    if stage == "build-data-layers":
        observations = [
            ProductObservation.model_validate(item)
            for item in _load_list(paths["parsed"] / "product_observations.json")
        ]
        pipeline_result = run_pipeline(observations, catalog)
        write_outputs(pipeline_result, paths["price"], "both")
        return pipeline_result.summary.model_dump(mode="json")

    if stage == "collect-reviews":
        source = FixtureReviewSource(review_fixtures)
        reviews = [
            review
            for product in catalog.products
            if product.enabled
            for review in source.collect(product)
        ]
        paths["reviews"].mkdir(parents=True, exist_ok=True)
        _write_json(
            paths["reviews"] / "collected_reviews.json",
            [item.model_dump(mode="json") for item in reviews],
        )
        return {"review_count": len(reviews)}

    if stage == "analyze-reviews":
        seqn = load_artifact_seqn(paths["price"] / "run_summary.json")
        review_llm = MockLLMProvider() if provider == "mock" else ConfiguredLLMProvider()
        analyses = run_review_analysis(
            catalog,
            CollectedReviewSource(paths["reviews"] / "collected_reviews.json"),
            review_llm,
        )
        _write_json(
            paths["reviews"] / "review_analyses.json",
            [item.model_dump(mode="json") for item in analyses],
        )
        comments = transform_comment_output(analyses, catalog, seqn=seqn)
        write_comment_outputs(comments, paths["reviews"])
        return comments.summary.model_dump(mode="json")

    if stage == "apply-business-rules":
        seqn = load_artifact_seqn(paths["price"] / "run_summary.json")
        trend_result = analyze_trends(
            load_target_rows(paths["price"] / "tgt.json"),
            catalog,
            load_rule_config(rules),
            seqn=seqn,
            comment_rows=load_json_rows(paths["reviews"] / "comment.json"),
            comment_evidence=load_json_rows(paths["reviews"] / "comment_evidence.json"),
        )
        write_trend_outputs(trend_result, paths["trend"])
        return trend_result.summary.model_dump(mode="json")

    if stage == "generate-recommendations":
        recommendation_provider = (
            MockRecommendationProvider() if provider == "mock" else ConfiguredLLMProvider()
        )
        recommendation_result = build_recommendations(
            load_json_rows(paths["trend"] / "overall_trend.json"),
            load_json_rows(paths["trend"] / "detected_events.json"),
            catalog,
            recommendation_provider,
            comment_evidence=load_json_rows(paths["reviews"] / "comment_evidence.json"),
        )
        write_recommendation_outputs(recommendation_result, paths["recommendations"])
        return recommendation_result.summary.model_dump(mode="json")

    if stage == "assemble-bundle":
        bundle = _assemble_bundle(output_dir, paths, provider, sheet_url)
        path = write_demo_bundle(bundle, output_dir)
        return {"seqn": bundle.seqn, "bundle": str(path)}

    raise ValueError(f"Unknown n8n stage: {stage}")


def _assemble_bundle(
    output_dir: Path,
    paths: dict[str, Path],
    provider: ProviderName,
    sheet_url: str,
) -> DemoBundle:
    del output_dir
    pipeline_summary = _load_object(paths["price"] / "run_summary.json")
    recommendation_summary = _load_object(paths["recommendations"] / "recommendation_summary.json")
    raw_recommendations = recommendation_summary.get("recommendations", [])
    if not isinstance(raw_recommendations, list):
        raise ValueError("recommendation_summary.json recommendations must be an array")
    recommendations = [
        StructuredRecommendation.model_validate(item) for item in raw_recommendations
    ]
    stg_rows = _load_list(paths["price"] / "stg.json")
    ods_rows = _load_list(paths["price"] / "ods.json")
    tgt_rows = _load_list(paths["price"] / "tgt.json")
    comment_rows = _load_list(paths["reviews"] / "comment.json")
    trend_rows = _load_list(paths["trend"] / "overall_trend.json")
    suggestion_rows = _load_list(paths["recommendations"] / "recent_suggestion.json")
    events = _load_list(paths["trend"] / "detected_events.json")
    rejected = _load_list(paths["price"] / "rejected.json")
    seqn = str(pipeline_summary["seqn"])
    generated_at = datetime.now(UTC)
    sheet_rows = {
        "STG": stg_rows,
        "ODS": ods_rows,
        "TGT": tgt_rows,
        "Comment": comment_rows,
        "Overall Trend": trend_rows,
        "Recent Suggestion": suggestion_rows,
    }
    bundle = DemoBundle(
        seqn=seqn,
        stg_rows=stg_rows,
        ods_rows=ods_rows,
        tgt_rows=tgt_rows,
        comment_rows=comment_rows,
        overall_trend_rows=trend_rows,
        recent_suggestion_rows=suggestion_rows,
        detected_events=events,
        run_summary=DemoRunSummary(
            seqn=seqn,
            mode="fixture",
            provider=provider,
            generated_at=generated_at,
            sheet_row_counts={name: len(rows) for name, rows in sheet_rows.items()},
            detected_event_count=len(events),
            recommendation_count=len(recommendations),
            rejected_row_count=len(rejected),
            actionable=bool(events),
        ),
        email_content=build_email(
            seqn,
            generated_at,
            tgt_rows,
            comment_rows,
            events,
            recommendations,
            sheet_url,
        ),
    )
    validate_bundle(bundle)
    return bundle


def _require(path: Path) -> None:
    if not path.is_file():
        raise ValueError(f"Required stage artifact is missing: {path}")


def _load_list(path: Path) -> list[dict[str, object]]:
    _require(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"{path.name} must contain a JSON array of objects")
    return payload


def _load_object(path: Path) -> dict[str, object]:
    _require(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return payload


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
