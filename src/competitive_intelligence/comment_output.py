"""Transform structured review analysis into Comment Sheet-compatible artifacts."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from competitive_intelligence.config import ProductCatalog
from competitive_intelligence.contracts import CommentRow, Vendor, sheet_headers
from competitive_intelligence.pipeline import generate_seqn
from competitive_intelligence.reviews import EvidenceTheme, NegativeTrend, ReviewAnalysis


class CommentEvidence(BaseModel):
    """Traceability that intentionally remains outside the Comment Sheet contract."""

    model_config = ConfigDict(extra="forbid")

    seqn: str
    product_id: str
    product_name: str
    vendor: Vendor
    status: Literal["success", "insufficient_data"]
    analyzed_review_count: int = Field(ge=0)
    supporting_review_ids: list[str]
    positive_theme_evidence: dict[str, list[str]]
    negative_theme_evidence: dict[str, list[str]]
    recurring_issue_evidence: dict[str, list[str]]
    negative_trend: NegativeTrend
    negative_trend_detected: bool | None
    prompt_version: str
    provider: str
    model: str
    warnings: list[str]


class CommentSummary(BaseModel):
    """Reconciliation metadata for one Comment export."""

    model_config = ConfigDict(extra="forbid")

    seqn: str
    schema_version: str
    input_analysis_count: int = Field(ge=0)
    comment_row_count: int = Field(ge=0)
    insufficient_data_count: int = Field(ge=0)
    product_order: list[str]


class CommentOutput(BaseModel):
    """In-memory Comment rows plus their non-Sheet audit artifacts."""

    model_config = ConfigDict(extra="forbid")

    rows: list[CommentRow]
    evidence: list[CommentEvidence]
    summary: CommentSummary


def _theme_slots(values: Sequence[str]) -> tuple[str, str, str]:
    selected = list(dict.fromkeys(value.strip() for value in values if value.strip()))[:3]
    padded = (selected + [""] * 3)[:3]
    return padded[0], padded[1], padded[2]


def _theme_evidence(themes: Sequence[EvidenceTheme]) -> dict[str, list[str]]:
    return {theme.theme: list(theme.supporting_review_ids) for theme in themes}


def _trend_boolean(trend: NegativeTrend) -> bool | None:
    if trend is NegativeTrend.INSUFFICIENT_EVIDENCE:
        return None
    return trend is NegativeTrend.DETECTED


def transform_comment_output(
    analyses: Sequence[ReviewAnalysis],
    catalog: ProductCatalog,
    *,
    seqn: str | None = None,
    schema_version: str = "1.0.0",
) -> CommentOutput:
    """Map one validated analysis per enabled product in catalog order."""
    run_seqn = seqn or generate_seqn()
    if not run_seqn.strip():
        raise ValueError("SEQN must not be blank")

    by_product: dict[str, ReviewAnalysis] = {}
    for analysis in analyses:
        if analysis.product_id in by_product:
            raise ValueError(f"Duplicate analysis for {analysis.product_id}")
        by_product[analysis.product_id] = analysis

    enabled = [product for product in catalog.products if product.enabled]
    enabled_ids = {product.product_id for product in enabled}
    unknown = set(by_product) - enabled_ids
    if unknown:
        raise ValueError(f"Analysis references unknown or disabled products: {sorted(unknown)}")

    rows: list[CommentRow] = []
    evidence: list[CommentEvidence] = []
    insufficient_count = 0
    for product in enabled:
        product_analysis = by_product.get(product.product_id)
        if product_analysis is None:
            raise ValueError(f"Missing analysis for {product.product_id}")

        insufficient = (
            product_analysis.negative_trend is NegativeTrend.INSUFFICIENT_EVIDENCE
            or "insufficient-data" in product_analysis.warnings
        )
        status: Literal["success", "insufficient_data"] = (
            "insufficient_data" if insufficient else "success"
        )
        if insufficient:
            insufficient_count += 1
        else:
            pros = _theme_slots([item.theme for item in product_analysis.positive_themes])
            cons = _theme_slots(
                [item.theme for item in product_analysis.negative_themes]
                + [item.theme for item in product_analysis.recurring_issues]
            )
            rows.append(
                CommentRow.model_validate(
                    {
                        "Product Name": product.product_name,
                        "Vendor": Vendor.AMAZON,
                        "Pros1": pros[0],
                        "Pros2": pros[1],
                        "Pros3": pros[2],
                        "Cons1": cons[0],
                        "Cons2": cons[1],
                        "Cons3": cons[2],
                        "Summary": product_analysis.summary,
                    }
                )
            )

        evidence.append(
            CommentEvidence(
                seqn=run_seqn,
                product_id=product.product_id,
                product_name=product.product_name,
                vendor=Vendor.AMAZON,
                status=status,
                analyzed_review_count=product_analysis.analyzed_review_count,
                supporting_review_ids=list(product_analysis.supporting_review_ids),
                positive_theme_evidence=_theme_evidence(product_analysis.positive_themes),
                negative_theme_evidence=_theme_evidence(product_analysis.negative_themes),
                recurring_issue_evidence=_theme_evidence(product_analysis.recurring_issues),
                negative_trend=product_analysis.negative_trend,
                negative_trend_detected=_trend_boolean(product_analysis.negative_trend),
                prompt_version=product_analysis.prompt_version,
                provider=product_analysis.provider,
                model=product_analysis.model,
                warnings=list(product_analysis.warnings),
            )
        )

    return CommentOutput(
        rows=rows,
        evidence=evidence,
        summary=CommentSummary(
            seqn=run_seqn,
            schema_version=schema_version,
            input_analysis_count=len(analyses),
            comment_row_count=len(rows),
            insufficient_data_count=insufficient_count,
            product_order=[product.product_id for product in enabled],
        ),
    )


def write_comment_outputs(result: CommentOutput, output_dir: Path) -> None:
    """Write exact-header Comment JSON/CSV plus evidence and run summary."""
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [row.model_dump(mode="json", by_alias=True) for row in result.rows]
    _write_json(output_dir / "comment.json", rows)
    with (output_dir / "comment.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sheet_headers(CommentRow))
        writer.writeheader()
        writer.writerows(rows)
    _write_json(
        output_dir / "comment_evidence.json",
        [item.model_dump(mode="json") for item in result.evidence],
    )
    _write_json(output_dir / "comment_summary.json", result.summary.model_dump(mode="json"))


def load_seqn_from_run_summary(path: Path) -> str:
    """Read the PR #5 run context without accepting unrelated fields as SEQN."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    seqn = payload.get("seqn") if isinstance(payload, dict) else None
    if not isinstance(seqn, str) or not seqn.strip():
        raise ValueError("Run summary must contain a non-empty string seqn")
    return seqn


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
