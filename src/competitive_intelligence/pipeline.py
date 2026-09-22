"""Deterministic STG/ODS/TGT transformations for offline fixture data."""

from __future__ import annotations

import csv
import json
import threading
import time
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from competitive_intelligence.config import ProductCatalog
from competitive_intelligence.contracts import PriceRow, TargetRow
from competitive_intelligence.parsing import ProductObservation

StageName = Literal["STG", "ODS", "TGT"]
OutputFormat = Literal["json", "csv", "both"]


class RejectedRecord(BaseModel):
    """A rejected input with an auditable stage, reason, and source identity."""

    model_config = ConfigDict(extra="forbid")

    stage: StageName
    reason: str
    source_identifier: str
    record: dict[str, Any]


class RunSummary(BaseModel):
    """Counts that reconcile one pipeline execution."""

    model_config = ConfigDict(extra="forbid")

    seqn: str
    stg_count: int = Field(ge=0)
    ods_accepted_count: int = Field(ge=0)
    ods_rejected_count: int = Field(ge=0)
    tgt_count: int = Field(ge=0)


class PipelineResult(BaseModel):
    """In-memory result for all three Sheet-compatible layers."""

    model_config = ConfigDict(extra="forbid")

    stg: list[dict[str, Any]]
    ods: list[PriceRow]
    tgt: list[TargetRow]
    rejected: list[RejectedRecord]
    summary: RunSummary


_seqn_lock = threading.Lock()
_last_seqn = 0


def generate_seqn() -> str:
    """Return a process-safe, time-sortable, 20-digit batch identifier."""
    global _last_seqn
    with _seqn_lock:
        candidate = time.time_ns()
        _last_seqn = max(candidate, _last_seqn + 1)
        return f"{_last_seqn:020d}"


def observation_to_stg(observation: ProductObservation, seqn: str) -> dict[str, Any]:
    """Map parser output to the exact STG headers without hiding incomplete evidence."""
    stock = {
        "in_stock": "In Stock",
        "out_of_stock": "Out of Stock",
        "unknown": "Unknown",
    }[observation.stock_status.value]
    return {
        "Item Number": observation.product_id,
        "Product Name": observation.product_name,
        "Vendor": observation.vendor.value,
        "Base Price": observation.base_price,
        "Final Price": observation.final_price,
        "Stock Status": stock,
        "Timestamp": observation.observed_at.isoformat(),
        "SEQN": seqn,
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime,)):
        return value.isoformat()
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_json_value(item) for item in value]
    return value


def _source_identifier(record: Mapping[str, Any], position: int) -> str:
    item = record.get("Item Number") or "unknown-product"
    vendor = record.get("Vendor") or "unknown-vendor"
    return f"{item}/{vendor}/row-{position}"


def _validation_reason(error: ValidationError) -> str:
    parts = []
    for issue in error.errors(include_url=False, include_context=False, include_input=False):
        location = ".".join(str(value) for value in issue["loc"])
        parts.append(f"{location}: {issue['msg']}")
    return "; ".join(parts)


def _normalize_identity(row: PriceRow, names: Mapping[str, str]) -> PriceRow:
    canonical_name = names.get(row.item_number)
    if canonical_name is None:
        raise ValueError(f"unknown product identity: {row.item_number}")
    return row.model_copy(update={"product_name": canonical_name})


def transform_ods(
    stg_rows: Sequence[Mapping[str, Any]], catalog: ProductCatalog
) -> tuple[list[PriceRow], list[RejectedRecord]]:
    """Validate, normalize, and de-duplicate STG rows without silent loss."""
    names = {product.product_id: product.product_name for product in catalog.products}
    accepted: list[PriceRow] = []
    rejected: list[RejectedRecord] = []
    seen: set[str] = set()
    for position, raw in enumerate(stg_rows, start=1):
        record = dict(raw)
        source = _source_identifier(record, position)
        try:
            row = _normalize_identity(PriceRow.model_validate(record), names)
        except ValidationError as exc:
            rejected.append(
                RejectedRecord(
                    stage="ODS",
                    reason=_validation_reason(exc),
                    source_identifier=source,
                    record=_json_value(record),
                )
            )
            continue
        except ValueError as exc:
            rejected.append(
                RejectedRecord(
                    stage="ODS",
                    reason=str(exc),
                    source_identifier=source,
                    record=_json_value(record),
                )
            )
            continue
        fingerprint = json.dumps(
            row.model_dump(mode="json", by_alias=True), sort_keys=True, separators=(",", ":")
        )
        if fingerprint in seen:
            rejected.append(
                RejectedRecord(
                    stage="ODS",
                    reason="exact duplicate",
                    source_identifier=source,
                    record=_json_value(record),
                )
            )
            continue
        seen.add(fingerprint)
        accepted.append(row)
    return accepted, rejected


def transform_tgt(rows: Sequence[PriceRow], catalog: ProductCatalog) -> list[TargetRow]:
    """Build one deterministic business row per product/vendor for the batch."""
    own_prices = {product.product_id: product.own_price for product in catalog.products}
    selected: dict[tuple[str, str], PriceRow] = {}
    for row in sorted(
        rows,
        key=lambda item: (
            item.item_number,
            item.vendor.value,
            item.timestamp.isoformat(),
            str(item.final_price),
        ),
    ):
        selected.setdefault((row.item_number, row.vendor.value), row)
    result = []
    for key in sorted(selected):
        row = selected[key]
        result.append(
            TargetRow.model_validate(
                {
                    "Item Number": row.item_number,
                    "Product Name": row.product_name,
                    "Vendor": row.vendor,
                    "Base Price": row.base_price,
                    "Final Price": row.final_price,
                    "My price": own_prices[row.item_number],
                    "Recent Stock": row.stock_status,
                    "Current Stock": row.stock_status,
                    "Timestamp": row.timestamp.isoformat(),
                }
            )
        )
    return result


def run_pipeline(
    observations: Sequence[ProductObservation],
    catalog: ProductCatalog,
    *,
    seqn_factory: Callable[[], str] = generate_seqn,
) -> PipelineResult:
    """Run the complete in-memory STG -> ODS -> TGT pipeline."""
    seqn = seqn_factory()
    stg = [observation_to_stg(item, seqn) for item in observations]
    ods, rejected = transform_ods(stg, catalog)
    tgt = transform_tgt(ods, catalog)
    return PipelineResult(
        stg=stg,
        ods=ods,
        tgt=tgt,
        rejected=rejected,
        summary=RunSummary(
            seqn=seqn,
            stg_count=len(stg),
            ods_accepted_count=len(ods),
            ods_rejected_count=len(rejected),
            tgt_count=len(tgt),
        ),
    )


def write_outputs(result: PipelineResult, output_dir: Path, output_format: OutputFormat) -> None:
    """Write Sheet-header JSON and/or CSV artifacts plus reconciliation metadata."""
    output_dir.mkdir(parents=True, exist_ok=True)
    datasets = {
        "stg": [_json_value(row) for row in result.stg],
        "ods": [row.model_dump(mode="json", by_alias=True) for row in result.ods],
        "tgt": [row.model_dump(mode="json", by_alias=True) for row in result.tgt],
    }
    if output_format in {"json", "both"}:
        for name, rows in datasets.items():
            _write_json(output_dir / f"{name}.json", rows)
    if output_format in {"csv", "both"}:
        for name, rows in datasets.items():
            _write_csv(output_dir / f"{name}.csv", rows)
    _write_json(
        output_dir / "rejected.json",
        [row.model_dump(mode="json") for row in result.rejected],
    )
    _write_json(output_dir / "run_summary.json", result.summary.model_dump(mode="json"))


def _write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
