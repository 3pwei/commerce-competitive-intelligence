"""Deterministic business rules and Overall Trend Sheet transformation."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from competitive_intelligence.config import ProductCatalog
from competitive_intelligence.contracts import (
    OverallTrendRow,
    StockStatus,
    TargetRow,
    Vendor,
    sheet_headers,
)


class RuleId(StrEnum):
    COMPETITOR_PRICE_LOWER = "COMPETITOR_PRICE_LOWER"
    LOWEST_COMPETITOR = "LOWEST_COMPETITOR"
    OUT_OF_STOCK = "OUT_OF_STOCK"
    BACK_IN_STOCK = "BACK_IN_STOCK"
    STOCK_STATUS_CHANGED = "STOCK_STATUS_CHANGED"
    RECURRING_NEGATIVE_ISSUE = "RECURRING_NEGATIVE_ISSUE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


Severity = Literal["info", "warning", "critical"]


class RuleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str
    severity: dict[RuleId, Severity]


class DetectedEvent(BaseModel):
    """Auditable result of one deterministic rule evaluation."""

    model_config = ConfigDict(extra="forbid")
    rule_id: RuleId
    product_id: str
    product_name: str
    vendor: Vendor | None
    severity: Severity
    seqn: str
    evidence: dict[str, Any]


class TrendWarning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    product_id: str
    vendor: Vendor | None
    message: str


class TrendSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")
    seqn: str
    rule_version: str
    snapshot_type: Literal["current_snapshot", "batch_comparison"]
    input_tgt_count: int = Field(ge=0)
    comment_row_count: int = Field(ge=0)
    overall_trend_row_count: int = Field(ge=0)
    event_count: int = Field(ge=0)
    warnings: list[TrendWarning]


class TrendResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rows: list[OverallTrendRow]
    events: list[DetectedEvent]
    summary: TrendSummary


def load_rule_config(path: Path) -> RuleConfig:
    return RuleConfig.model_validate_json(path.read_text(encoding="utf-8"))


def _event(
    rule: RuleId,
    row: TargetRow,
    product_id: str,
    seqn: str,
    rules: RuleConfig,
    evidence: dict[str, Any],
) -> DetectedEvent:
    return DetectedEvent(
        rule_id=rule,
        product_id=product_id,
        product_name=row.product_name,
        vendor=row.vendor,
        severity=rules.severity[rule],
        seqn=seqn,
        evidence=evidence,
    )


def _price_evidence(row: TargetRow) -> dict[str, str]:
    difference = row.own_price - row.final_price
    percentage = Decimal("0") if row.own_price == 0 else difference / row.own_price * 100
    return {
        "final_price": str(row.final_price),
        "own_price": str(row.own_price),
        "difference_amount": str(difference),
        "difference_percent": str(percentage.quantize(Decimal("0.01"))),
    }


def analyze_trends(
    tgt_rows: Sequence[TargetRow | Mapping[str, Any]],
    catalog: ProductCatalog,
    rules: RuleConfig,
    *,
    seqn: str,
    comment_rows: Sequence[Mapping[str, Any]] = (),
    comment_evidence: Sequence[Mapping[str, Any]] = (),
    previous_rows: Sequence[TargetRow | Mapping[str, Any]] | None = None,
) -> TrendResult:
    """Evaluate price, stock, and validated review signals without an LLM."""
    if not seqn.strip():
        raise ValueError("SEQN must not be blank")
    products = {product.product_id: product for product in catalog.products if product.enabled}
    names = {product.product_name: product.product_id for product in products.values()}
    grouped: dict[str, list[TargetRow]] = defaultdict(list)
    warnings: list[TrendWarning] = []
    for raw_row in tgt_rows:
        if isinstance(raw_row, TargetRow):
            row = raw_row
        else:
            try:
                row = TargetRow.model_validate(raw_row)
            except ValidationError as exc:
                name = raw_row.get("Product Name")
                invalid_product_id = names.get(
                    str(name), str(raw_row.get("Item Number", "unknown"))
                )
                vendor_value = raw_row.get("Vendor")
                try:
                    vendor = Vendor(str(vendor_value))
                except ValueError:
                    vendor = None
                warnings.append(
                    TrendWarning(
                        product_id=invalid_product_id,
                        vendor=vendor,
                        message=f"Invalid or missing Final Price: {exc.errors()[0]['msg']}",
                    )
                )
                continue
        product_id = names.get(row.product_name)
        if product_id is None:
            raise ValueError(f"TGT references unknown product name: {row.product_name}")
        grouped[product_id].append(row)

    validated_previous = (
        [
            row if isinstance(row, TargetRow) else TargetRow.model_validate(row)
            for row in previous_rows
        ]
        if previous_rows is not None
        else []
    )
    previous = {(names[row.product_name], row.vendor): row for row in validated_previous}
    events: list[DetectedEvent] = []
    row_events: dict[tuple[str, Vendor], list[DetectedEvent]] = defaultdict(list)

    for product_id in sorted(products):
        rows = grouped.get(product_id, [])
        if not rows:
            warnings.append(TrendWarning(product_id=product_id, vendor=None, message="No TGT data"))
            continue
        lowest = min(row.final_price for row in rows)
        for row in sorted(rows, key=lambda item: (item.final_price, item.vendor.value)):
            created: list[DetectedEvent] = []
            if row.final_price < row.own_price:
                created.append(
                    _event(
                        RuleId.COMPETITOR_PRICE_LOWER,
                        row,
                        product_id,
                        seqn,
                        rules,
                        _price_evidence(row),
                    )
                )
            if row.final_price == lowest:
                evidence = _price_evidence(row) | {
                    "rank": "1",
                    "tie": str(sum(item.final_price == lowest for item in rows) > 1).lower(),
                }
                created.append(
                    _event(RuleId.LOWEST_COMPETITOR, row, product_id, seqn, rules, evidence)
                )
            if row.current_stock is StockStatus.OUT_OF_STOCK:
                created.append(
                    _event(
                        RuleId.OUT_OF_STOCK,
                        row,
                        product_id,
                        seqn,
                        rules,
                        {"current_stock": row.current_stock.value},
                    )
                )
            if (
                previous_rows is not None
                and (old := previous.get((product_id, row.vendor))) is not None
                and old.current_stock != row.current_stock
            ):
                created.append(
                    _event(
                        RuleId.STOCK_STATUS_CHANGED,
                        row,
                        product_id,
                        seqn,
                        rules,
                        {
                            "previous_stock": old.current_stock.value,
                            "current_stock": row.current_stock.value,
                        },
                    )
                )
                if (
                    old.current_stock is StockStatus.OUT_OF_STOCK
                    and row.current_stock is StockStatus.IN_STOCK
                ):
                    created.append(
                        _event(
                            RuleId.BACK_IN_STOCK,
                            row,
                            product_id,
                            seqn,
                            rules,
                            {
                                "previous_stock": old.current_stock.value,
                                "current_stock": row.current_stock.value,
                            },
                        )
                    )
            events.extend(created)
            row_events[(product_id, row.vendor)].extend(created)

    for warning in warnings:
        product = products.get(warning.product_id)
        events.append(
            DetectedEvent(
                rule_id=RuleId.INSUFFICIENT_DATA,
                product_id=warning.product_id,
                product_name=product.product_name if product else warning.product_id,
                vendor=warning.vendor,
                severity=rules.severity[RuleId.INSUFFICIENT_DATA],
                seqn=seqn,
                evidence={"warning": warning.message},
            )
        )

    comment_names = {str(row.get("Product Name")) for row in comment_rows}
    for review_evidence in comment_evidence:
        evidence_seqn = review_evidence.get("seqn")
        if evidence_seqn is not None and evidence_seqn != seqn:
            raise ValueError("TGT and Comment evidence must belong to the same SEQN")
        review_product_id = review_evidence.get("product_id")
        if (
            not isinstance(review_product_id, str)
            or review_product_id not in products
            or review_evidence.get("negative_trend_detected") is not True
        ):
            continue
        product = products[review_product_id]
        if product.product_name not in comment_names:
            continue
        amazon_row = next(
            (row for row in grouped[review_product_id] if row.vendor is Vendor.AMAZON), None
        )
        if amazon_row is None:
            continue
        event = _event(
            RuleId.RECURRING_NEGATIVE_ISSUE,
            amazon_row,
            review_product_id,
            seqn,
            rules,
            {
                "recurring_issue_evidence": review_evidence.get("recurring_issue_evidence", {}),
                "supporting_review_ids": review_evidence.get("supporting_review_ids", []),
            },
        )
        events.append(event)
        row_events[(review_product_id, Vendor.AMAZON)].append(event)

    output_rows = []
    for product_id in sorted(grouped):
        for row in sorted(grouped[product_id], key=lambda item: item.vendor.value):
            applicable = row_events[(product_id, row.vendor)]
            labels = [item.rule_id.value for item in applicable]
            observation = "; ".join(labels) if labels else "No rule-triggered event"
            output_rows.append(
                OverallTrendRow.model_validate(
                    {
                        "Product Name": row.product_name,
                        "Vendor": row.vendor,
                        "Overall Trend": " | ".join(labels) or "CURRENT_SNAPSHOT",
                        "Observation": observation,
                    }
                )
            )

    events.sort(
        key=lambda item: (
            item.product_id,
            item.vendor.value if item.vendor else "",
            item.rule_id.value,
        )
    )
    return TrendResult(
        rows=output_rows,
        events=events,
        summary=TrendSummary(
            seqn=seqn,
            rule_version=rules.version,
            snapshot_type="batch_comparison" if previous_rows is not None else "current_snapshot",
            input_tgt_count=len(tgt_rows),
            comment_row_count=len(comment_rows),
            overall_trend_row_count=len(output_rows),
            event_count=len(events),
            warnings=warnings,
        ),
    )


def load_target_rows(path: Path) -> list[TargetRow | Mapping[str, Any]]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError("TGT input must be a JSON array")
    if not all(isinstance(row, dict) for row in value):
        raise ValueError("TGT input rows must be JSON objects")
    return value


def load_json_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError(f"{path.name} must be a JSON array of objects")
    return value


def load_artifact_seqn(path: Path) -> str:
    value = json.loads(path.read_text(encoding="utf-8"))
    seqn = value.get("seqn") if isinstance(value, dict) else None
    if not isinstance(seqn, str) or not seqn.strip():
        raise ValueError(f"{path.name} must contain a non-empty string seqn")
    return seqn


def write_trend_outputs(result: TrendResult, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = [row.model_dump(mode="json", by_alias=True) for row in result.rows]
    (output_dir / "overall_trend.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    with (output_dir / "overall_trend.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=sheet_headers(OverallTrendRow))
        writer.writeheader()
        writer.writerows(rows)
    (output_dir / "detected_events.json").write_text(
        json.dumps(
            [event.model_dump(mode="json") for event in result.events], indent=2, ensure_ascii=False
        )
        + "\n",
        encoding="utf-8",
    )
    (output_dir / "trend_summary.json").write_text(
        result.summary.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
