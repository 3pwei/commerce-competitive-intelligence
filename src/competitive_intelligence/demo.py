"""End-to-end demo bundle assembly for n8n orchestration."""

from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from competitive_intelligence.capture import capture_live, replay
from competitive_intelligence.comment_output import transform_comment_output
from competitive_intelligence.config import load_product_catalog
from competitive_intelligence.contracts import SHEET_MODELS, SheetRow, sheet_headers
from competitive_intelligence.pipeline import run_pipeline
from competitive_intelligence.recommendations import (
    MockRecommendationProvider,
    StructuredRecommendation,
    build_recommendations,
)
from competitive_intelligence.reviews import (
    ConfiguredLLMProvider,
    FixtureReviewSource,
    MockLLMProvider,
    run_review_analysis,
)
from competitive_intelligence.trends import analyze_trends, load_rule_config

Mode = Literal["fixture", "live"]
ProviderName = Literal["mock", "configured"]
SHEET_KEYS = {
    "STG": "stg_rows",
    "ODS": "ods_rows",
    "TGT": "tgt_rows",
    "Comment": "comment_rows",
    "Overall Trend": "overall_trend_rows",
    "Recent Suggestion": "recent_suggestion_rows",
}


class EmailContent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    subject: str
    text: str
    html: str


class DemoRunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seqn: str
    mode: Mode
    provider: ProviderName
    generated_at: datetime
    sheet_row_counts: dict[str, int]
    detected_event_count: int = Field(ge=0)
    recommendation_count: int = Field(ge=0)
    rejected_row_count: int = Field(ge=0)
    actionable: bool


class DemoBundle(BaseModel):
    """Single hand-off contract consumed by the n8n workflow."""

    model_config = ConfigDict(extra="forbid")
    seqn: str
    stg_rows: list[dict[str, Any]]
    ods_rows: list[dict[str, Any]]
    tgt_rows: list[dict[str, Any]]
    comment_rows: list[dict[str, Any]]
    overall_trend_rows: list[dict[str, Any]]
    recent_suggestion_rows: list[dict[str, Any]]
    detected_events: list[dict[str, Any]]
    run_summary: DemoRunSummary
    email_content: EmailContent


def _dump_rows(rows: Sequence[SheetRow]) -> list[dict[str, Any]]:
    return [row.model_dump(mode="json", by_alias=True) for row in rows]


def validate_sheet_rows(sheet_name: str, rows: Sequence[Mapping[str, Any]]) -> None:
    """Validate every row and exact header order before any external delivery."""
    model = SHEET_MODELS[sheet_name]
    expected = sheet_headers(model)
    for position, row in enumerate(rows, start=1):
        if list(row) != expected:
            raise ValueError(f"{sheet_name} row {position} headers do not match contract")
        model.model_validate(row)


def validate_bundle(bundle: DemoBundle) -> None:
    if bundle.seqn != bundle.run_summary.seqn:
        raise ValueError("bundle and summary SEQN do not match")
    payload = bundle.model_dump(mode="json")
    for sheet_name, key in SHEET_KEYS.items():
        rows = payload[key]
        if not rows:
            raise ValueError(f"{sheet_name} must contain at least one demo row")
        validate_sheet_rows(sheet_name, rows)
        if bundle.run_summary.sheet_row_counts[sheet_name] != len(rows):
            raise ValueError(f"{sheet_name} row count does not reconcile")
    if any(row.get("SEQN") != bundle.seqn for row in bundle.stg_rows + bundle.ods_rows):
        raise ValueError("STG/ODS rows must use the bundle SEQN")

    def identity(row: Mapping[str, Any]) -> tuple[str, str]:
        return str(row["Product Name"]), str(row["Vendor"])

    ods_keys = {identity(row) for row in bundle.ods_rows}
    tgt_keys = {identity(row) for row in bundle.tgt_rows}
    trend_keys = {identity(row) for row in bundle.overall_trend_rows}
    if ods_keys != tgt_keys or tgt_keys != trend_keys:
        raise ValueError("ODS, TGT, and Overall Trend identities do not reconcile")
    if not {identity(row) for row in bundle.comment_rows}.issubset(tgt_keys):
        raise ValueError("Comment identities must exist in TGT")
    if not {identity(row) for row in bundle.recent_suggestion_rows}.issubset(tgt_keys):
        raise ValueError("Recent Suggestion identities must exist in TGT")


def _event_lines(events: Sequence[Mapping[str, Any]]) -> list[str]:
    if not events:
        return ["No actionable event"]
    return [
        f"{event['severity'].upper()}: {event['product_name']} / "
        f"{event.get('vendor') or 'all vendors'} / {event['rule_id']}"
        for event in events
    ]


def build_email(
    seqn: str,
    generated_at: datetime,
    tgt_rows: Sequence[Mapping[str, Any]],
    comment_rows: Sequence[Mapping[str, Any]],
    events: Sequence[Mapping[str, Any]],
    recommendations: Sequence[StructuredRecommendation],
    sheet_url: str,
) -> EmailContent:
    ranked = sorted(tgt_rows, key=lambda row: (str(row["Product Name"]), float(row["Final Price"])))
    price_lines = [
        f"{row['Product Name']}: {row['Vendor']} {row['Final Price']} (own {row['My price']})"
        for row in ranked
    ]
    lower = [
        f"{row['Product Name']} / {row['Vendor']}: {row['Final Price']} < {row['My price']}"
        for row in ranked
        if float(row["Final Price"]) < float(row["My price"])
    ] or ["None"]
    stock = [f"{row['Product Name']} / {row['Vendor']}: {row['Current Stock']}" for row in ranked]
    review = [f"{row['Product Name']}: {row['Summary']}" for row in comment_rows] or [
        "No review summary"
    ]
    suggestion = [f"{item.product_id}: {item.recommended_action}" for item in recommendations] or [
        "No actionable event"
    ]
    sections = [
        ("Price ranking", price_lines),
        ("Competitors below own price", lower),
        ("Stock status", stock),
        ("Review risk summary", review),
        ("Detected events", _event_lines(events)),
        ("AI recommendations", suggestion),
    ]
    text_parts = [
        f"Competitive Intelligence Demo\nSEQN: {seqn}\nRun time: {generated_at.isoformat()}"
    ]
    html_parts = [
        "<h1>Competitive Intelligence Demo</h1>",
        f"<p><strong>SEQN:</strong> {html.escape(seqn)}<br>",
        f"<strong>Run time:</strong> {html.escape(generated_at.isoformat())}</p>",
    ]
    for title, lines in sections:
        text_parts.append(f"\n{title}\n" + "\n".join(f"- {line}" for line in lines))
        html_parts.append(f"<h2>{html.escape(title)}</h2><ul>")
        html_parts.extend(f"<li>{html.escape(line)}</li>" for line in lines)
        html_parts.append("</ul>")
    if sheet_url:
        text_parts.append(f"\nGoogle Sheet: {sheet_url}")
        html_parts.append(
            f'<p><a href="{html.escape(sheet_url, quote=True)}">Open Google Sheet</a></p>'
        )
    return EmailContent(
        subject=f"Competitive intelligence demo — {seqn}",
        text="\n".join(text_parts),
        html="".join(html_parts),
    )


def run_demo(
    *,
    mode: Mode = "fixture",
    provider: ProviderName = "mock",
    product_config: Path = Path("config/products.example.json"),
    product_fixtures: Path = Path("fixtures/product-pages/manifest.json"),
    review_fixtures: Path = Path("fixtures/reviews/manifest.json"),
    rules: Path = Path("config/business-rules.v1.json"),
    live_output: Path = Path("fixtures/live"),
    sheet_url: str = "",
) -> DemoBundle:
    """Execute all Python business stages and return one validated bundle."""
    catalog = load_product_catalog(product_config)
    if mode == "fixture":
        observations = replay(product_fixtures)
    else:
        observations, failures = capture_live(catalog, live_output)
        if failures:
            raise RuntimeError(f"live capture failed for {len(failures)} listing(s)")
    pipeline = run_pipeline(observations, catalog)
    llm = MockLLMProvider() if provider == "mock" else ConfiguredLLMProvider()
    analyses = run_review_analysis(catalog, FixtureReviewSource(review_fixtures), llm)
    comments = transform_comment_output(analyses, catalog, seqn=pipeline.summary.seqn)
    trends = analyze_trends(
        pipeline.tgt,
        catalog,
        load_rule_config(rules),
        seqn=pipeline.summary.seqn,
        comment_rows=_dump_rows(comments.rows),
        comment_evidence=[item.model_dump(mode="json") for item in comments.evidence],
    )
    recommendation_provider = MockRecommendationProvider() if provider == "mock" else llm
    recommendations = build_recommendations(
        _dump_rows(trends.rows),
        [item.model_dump(mode="json") for item in trends.events],
        catalog,
        recommendation_provider,
        comment_evidence=[item.model_dump(mode="json") for item in comments.evidence],
    )
    generated_at = datetime.now(UTC)
    sheet_rows = {
        "STG": [dict(row) for row in pipeline.stg],
        "ODS": _dump_rows(pipeline.ods),
        "TGT": _dump_rows(pipeline.tgt),
        "Comment": _dump_rows(comments.rows),
        "Overall Trend": _dump_rows(trends.rows),
        "Recent Suggestion": _dump_rows(recommendations.rows),
    }
    event_rows = [item.model_dump(mode="json") for item in trends.events]
    bundle = DemoBundle(
        seqn=pipeline.summary.seqn,
        stg_rows=sheet_rows["STG"],
        ods_rows=sheet_rows["ODS"],
        tgt_rows=sheet_rows["TGT"],
        comment_rows=sheet_rows["Comment"],
        overall_trend_rows=sheet_rows["Overall Trend"],
        recent_suggestion_rows=sheet_rows["Recent Suggestion"],
        detected_events=event_rows,
        run_summary=DemoRunSummary(
            seqn=pipeline.summary.seqn,
            mode=mode,
            provider=provider,
            generated_at=generated_at,
            sheet_row_counts={name: len(rows) for name, rows in sheet_rows.items()},
            detected_event_count=len(event_rows),
            recommendation_count=len(recommendations.recommendations),
            rejected_row_count=len(pipeline.rejected),
            actionable=bool(event_rows),
        ),
        email_content=build_email(
            pipeline.summary.seqn,
            generated_at,
            sheet_rows["TGT"],
            sheet_rows["Comment"],
            event_rows,
            recommendations.recommendations,
            sheet_url,
        ),
    )
    validate_bundle(bundle)
    return bundle


def write_demo_bundle(bundle: DemoBundle, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / "demo_bundle.json"
    path.write_text(bundle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path
