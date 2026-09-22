"""Offline STG/ODS/TGT pipeline tests."""

import json
from pathlib import Path

import pytest

from competitive_intelligence.capture import replay
from competitive_intelligence.config import load_product_catalog
from competitive_intelligence.pipeline import (
    generate_seqn,
    run_pipeline,
    transform_ods,
    write_outputs,
)

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "fixtures/product-pages/manifest.json"
CATALOG = ROOT / "config/products.example.json"


def valid_stg_row() -> dict[str, object]:
    return {
        "Item Number": "apple-airpods-pro-2",
        "Product Name": "Retailer title",
        "Vendor": "Amazon.com",
        "Base Price": None,
        "Final Price": "189.99",
        "Stock Status": "In Stock",
        "Timestamp": "2026-09-22T00:00:00Z",
        "SEQN": "00000000000000000001",
    }


def test_nine_fixtures_run_through_all_layers_deterministically() -> None:
    observations = replay(MANIFEST)
    catalog = load_product_catalog(CATALOG)
    first = run_pipeline(observations, catalog, seqn_factory=lambda: "fixed-seqn")
    second = run_pipeline(observations, catalog, seqn_factory=lambda: "fixed-seqn")

    assert first == second
    assert len(first.stg) == len(first.ods) == len(first.tgt) == 9
    assert first.rejected == []
    assert first.summary.stg_count == (
        first.summary.ods_accepted_count + first.summary.ods_rejected_count
    )
    assert {row.seqn for row in first.ods} == {"fixed-seqn"}
    assert [(row.item_number, row.vendor.value) for row in first.tgt] == sorted(
        (row.item_number, row.vendor.value) for row in first.tgt
    )


@pytest.mark.parametrize(
    ("field", "value", "reason_fragment"),
    [
        ("Final Price", "not-a-price", "Final Price"),
        ("Stock Status", "Available", "Stock Status"),
        ("Timestamp", "2026-09-22 00:00:00", "Timestamp"),
    ],
)
def test_invalid_ods_rows_are_rejected_with_reasons(
    field: str, value: str, reason_fragment: str
) -> None:
    row = valid_stg_row()
    row[field] = value
    accepted, rejected = transform_ods([row], load_product_catalog(CATALOG))
    assert accepted == []
    assert len(rejected) == 1
    assert rejected[0].stage == "ODS"
    assert reason_fragment in rejected[0].reason
    assert rejected[0].source_identifier.startswith("apple-airpods-pro-2/")


def test_exact_duplicate_is_rejected_and_missing_base_price_is_preserved() -> None:
    row = valid_stg_row()
    accepted, rejected = transform_ods([row, dict(row)], load_product_catalog(CATALOG))
    assert len(accepted) == 1
    assert accepted[0].base_price is None
    assert len(rejected) == 1
    assert rejected[0].reason == "exact duplicate"
    assert len([row, dict(row)]) == len(accepted) + len(rejected)


def test_seqn_is_unique_and_sortable() -> None:
    values = [generate_seqn() for _ in range(3)]
    assert values == sorted(values)
    assert len(set(values)) == 3
    assert all(len(value) == 20 and value.isdigit() for value in values)


def test_json_and_csv_outputs_use_contract_headers(tmp_path: Path) -> None:
    result = run_pipeline(
        replay(MANIFEST), load_product_catalog(CATALOG), seqn_factory=lambda: "fixed-seqn"
    )
    write_outputs(result, tmp_path, "both")
    expected = {
        "stg.json",
        "ods.json",
        "tgt.json",
        "stg.csv",
        "ods.csv",
        "tgt.csv",
        "rejected.json",
        "run_summary.json",
    }
    assert {path.name for path in tmp_path.iterdir()} == expected
    stg = json.loads((tmp_path / "stg.json").read_text(encoding="utf-8"))
    assert list(stg[0]) == [
        "Item Number",
        "Product Name",
        "Vendor",
        "Base Price",
        "Final Price",
        "Stock Status",
        "Timestamp",
        "SEQN",
    ]
