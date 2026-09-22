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
from competitive_intelligence.pipeline import run_pipeline, write_outputs
from competitive_intelligence.reviews import (
    ConfiguredLLMProvider,
    FixtureReviewSource,
    MockLLMProvider,
    run_review_analysis,
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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the placeholder CLI."""
    args = build_parser().parse_args(argv)
    if args.command == "comment-output":
        catalog = load_product_catalog(args.config)
        provider = MockLLMProvider() if args.provider == "mock" else ConfiguredLLMProvider()
        analyses = run_review_analysis(catalog, FixtureReviewSource(args.fixtures), provider)
        seqn = load_seqn_from_run_summary(args.run_summary) if args.run_summary else args.seqn
        comment_result = transform_comment_output(analyses, catalog, seqn=seqn)
        write_comment_outputs(comment_result, args.output_dir)
        print(comment_result.summary.model_dump_json(indent=2))
        return 0
    if args.command == "reviews":
        catalog = load_product_catalog(args.config)
        provider = MockLLMProvider() if args.provider == "mock" else ConfiguredLLMProvider()
        analyses = run_review_analysis(catalog, FixtureReviewSource(args.fixtures), provider)
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
