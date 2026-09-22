"""Command-line entry point for the demo project."""

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from competitive_intelligence.capture import capture_live, replay
from competitive_intelligence.comment_output import (
    load_seqn_from_run_summary,
    transform_comment_output,
    write_comment_outputs,
)
from competitive_intelligence.config import load_product_catalog
from competitive_intelligence.demo import run_demo, write_demo_bundle
from competitive_intelligence.pipeline import run_pipeline, write_outputs
from competitive_intelligence.recommendations import (
    MockRecommendationProvider,
    build_recommendations,
    write_recommendation_outputs,
)
from competitive_intelligence.reviews import (
    ConfiguredLLMProvider,
    FixtureReviewSource,
    MockLLMProvider,
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


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(
        prog="competitive-intelligence",
        description="Competitive pricing and review analysis demo.",
    )
    subparsers = parser.add_subparsers(dest="command")
    capture = subparsers.add_parser("capture", help="Capture or replay product listings")
    capture.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    capture.add_argument("--config", type=Path, default=Path("config/products.example.json"))
    capture.add_argument(
        "--fixtures", type=Path, default=Path("fixtures/product-pages/manifest.json")
    )
    capture.add_argument("--live-output", type=Path, default=Path("fixtures/live"))
    pipeline = subparsers.add_parser("pipeline", help="Build offline STG/ODS/TGT outputs")
    pipeline.add_argument("--mode", choices=("fixture",), default="fixture")
    pipeline.add_argument("--config", type=Path, default=Path("config/products.example.json"))
    pipeline.add_argument(
        "--fixtures", type=Path, default=Path("fixtures/product-pages/manifest.json")
    )
    pipeline.add_argument("--output-dir", type=Path, required=True)
    pipeline.add_argument("--format", choices=("json", "csv", "both"), default="json")
    reviews = subparsers.add_parser("reviews", help="Analyze normalized Amazon reviews")
    reviews.add_argument("--mode", choices=("fixture",), default="fixture")
    reviews.add_argument("--provider", choices=("mock", "configured"), default="mock")
    reviews.add_argument("--config", type=Path, default=Path("config/products.example.json"))
    reviews.add_argument("--fixtures", type=Path, default=Path("fixtures/reviews/manifest.json"))
    comment = subparsers.add_parser("comment-output", help="Build offline Comment outputs")
    comment.add_argument("--mode", choices=("fixture",), default="fixture")
    comment.add_argument("--provider", choices=("mock", "configured"), default="mock")
    comment.add_argument("--config", type=Path, default=Path("config/products.example.json"))
    comment.add_argument("--fixtures", type=Path, default=Path("fixtures/reviews/manifest.json"))
    comment.add_argument("--output-dir", type=Path, required=True)
    seqn_group = comment.add_mutually_exclusive_group()
    seqn_group.add_argument("--seqn")
    seqn_group.add_argument("--run-summary", type=Path)
    trend = subparsers.add_parser("overall-trend", help="Build deterministic Overall Trend outputs")
    trend.add_argument("--tgt", type=Path, required=True)
    trend.add_argument("--comment", type=Path, required=True)
    trend.add_argument("--output-dir", type=Path, required=True)
    trend.add_argument("--config", type=Path, default=Path("config/products.example.json"))
    trend.add_argument("--rules", type=Path, default=Path("config/business-rules.v1.json"))
    trend.add_argument("--previous-tgt", type=Path)
    recommendation = subparsers.add_parser(
        "recommendations", help="Build evidence-bound Recent Suggestion outputs"
    )
    recommendation.add_argument("--trend", type=Path, required=True)
    recommendation.add_argument("--events", type=Path, required=True)
    recommendation.add_argument("--provider", choices=("mock", "configured"), default="mock")
    recommendation.add_argument("--output-dir", type=Path, required=True)
    recommendation.add_argument("--config", type=Path, default=Path("config/products.example.json"))
    recommendation.add_argument("--comment-evidence", type=Path)
    demo = subparsers.add_parser("demo-run", help="Build the complete validated n8n bundle")
    demo.add_argument("--mode", choices=("fixture", "live"), default="fixture")
    demo.add_argument("--provider", choices=("mock", "configured"), default="mock")
    demo.add_argument("--output-dir", type=Path, required=True)
    demo.add_argument("--config", type=Path, default=Path("config/products.example.json"))
    demo.add_argument("--fixtures", type=Path, default=Path("fixtures/product-pages/manifest.json"))
    demo.add_argument(
        "--review-fixtures", type=Path, default=Path("fixtures/reviews/manifest.json")
    )
    demo.add_argument("--rules", type=Path, default=Path("config/business-rules.v1.json"))
    demo.add_argument("--live-output", type=Path, default=Path("fixtures/live"))
    demo.add_argument(
        "--sheet-url",
        default="",
        help="Optional Google Sheet URL used only in the email preview",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the placeholder CLI."""
    args = build_parser().parse_args(argv)
    if args.command == "demo-run":
        bundle = run_demo(
            mode=args.mode,
            provider=args.provider,
            product_config=args.config,
            product_fixtures=args.fixtures,
            review_fixtures=args.review_fixtures,
            rules=args.rules,
            live_output=args.live_output,
            sheet_url=args.sheet_url,
        )
        path = write_demo_bundle(bundle, args.output_dir)
        print(json.dumps({"seqn": bundle.seqn, "bundle": str(path)}, indent=2))
        return 0
    if args.command == "recommendations":
        recommendation_provider = (
            MockRecommendationProvider() if args.provider == "mock" else ConfiguredLLMProvider()
        )
        comment_evidence_path = args.comment_evidence or args.trend.with_name(
            "comment_evidence.json"
        )
        recommendation_result = build_recommendations(
            load_json_rows(args.trend),
            load_json_rows(args.events),
            load_product_catalog(args.config),
            recommendation_provider,
            comment_evidence=load_json_rows(comment_evidence_path),
        )
        write_recommendation_outputs(recommendation_result, args.output_dir)
        print(recommendation_result.summary.model_dump_json(indent=2))
        return 0
    if args.command == "overall-trend":
        run_seqn = load_artifact_seqn(args.tgt.with_name("run_summary.json"))
        comment_summary = args.comment.with_name("comment_summary.json")
        if comment_summary.exists() and load_artifact_seqn(comment_summary) != run_seqn:
            raise ValueError("TGT and Comment inputs must belong to the same SEQN")
        trend_result = analyze_trends(
            load_target_rows(args.tgt),
            load_product_catalog(args.config),
            load_rule_config(args.rules),
            seqn=run_seqn,
            comment_rows=load_json_rows(args.comment),
            comment_evidence=load_json_rows(args.comment.with_name("comment_evidence.json")),
            previous_rows=load_target_rows(args.previous_tgt) if args.previous_tgt else None,
        )
        write_trend_outputs(trend_result, args.output_dir)
        print(trend_result.summary.model_dump_json(indent=2))
        return 0
    if args.command == "comment-output":
        catalog = load_product_catalog(args.config)
        review_provider = MockLLMProvider() if args.provider == "mock" else ConfiguredLLMProvider()
        analyses = run_review_analysis(catalog, FixtureReviewSource(args.fixtures), review_provider)
        seqn = load_seqn_from_run_summary(args.run_summary) if args.run_summary else args.seqn
        comment_result = transform_comment_output(analyses, catalog, seqn=seqn)
        write_comment_outputs(comment_result, args.output_dir)
        print(comment_result.summary.model_dump_json(indent=2))
        return 0
    if args.command == "reviews":
        catalog = load_product_catalog(args.config)
        review_provider = MockLLMProvider() if args.provider == "mock" else ConfiguredLLMProvider()
        analyses = run_review_analysis(catalog, FixtureReviewSource(args.fixtures), review_provider)
        print(json.dumps([item.model_dump(mode="json") for item in analyses], indent=2))
        return 0
    if args.command == "pipeline":
        observations = replay(args.fixtures)
        catalog = load_product_catalog(args.config)
        pipeline_result = run_pipeline(observations, catalog)
        write_outputs(pipeline_result, args.output_dir, args.format)
        print(pipeline_result.summary.model_dump_json(indent=2))
        return 0
    if args.command != "capture":
        return 0
    if args.mode == "fixture":
        observations = replay(args.fixtures)
        print(json.dumps([item.model_dump(mode="json") for item in observations], indent=2))
        return 0
    catalog = load_product_catalog(args.config)
    observations, failures = capture_live(catalog, args.live_output)
    print(json.dumps({"captured": len(observations), "failed": len(failures)}, indent=2))
    return 1 if failures else 0
