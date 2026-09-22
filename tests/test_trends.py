"""Deterministic business-rule and Overall Trend contract tests."""

import csv
import json
from pathlib import Path

import pytest

from competitive_intelligence.config import load_product_catalog
from competitive_intelligence.contracts import OverallTrendRow, TargetRow, sheet_headers
from competitive_intelligence.trends import (
    RuleId,
    analyze_trends,
    load_rule_config,
    write_trend_outputs,
)

ROOT = Path(__file__).parents[1]
CATALOG = load_product_catalog(ROOT / "config/products.example.json")
RULES = load_rule_config(ROOT / "config/business-rules.v1.json")


def target(
    product: int = 0, vendor: str = "amazon", price: str = "199.00", stock: str = "In Stock"
) -> TargetRow:
    configured = CATALOG.products[product]
    return TargetRow.model_validate(
        {
            "Item Number": configured.product_id,
            "Product Name": configured.product_name,
            "Vendor": vendor,
            "Base Price": None,
            "Final Price": price,
            "My price": configured.own_price,
            "Recent Stock": stock,
            "Current Stock": stock,
            "Timestamp": "2026-09-22T00:00:00Z",
        }
    )


def all_products() -> list[TargetRow]:
    return [
        target(index, vendor, str(CATALOG.products[index].own_price - 10))
        for index in range(3)
        for vendor in ("amazon", "walmart", "bestbuy")
    ]


def test_three_products_rank_ties_and_compare_own_price_with_decimal() -> None:
    rows = [
        target(vendor="amazon", price="199.00"),
        target(vendor="walmart", price="199.00"),
        target(vendor="bestbuy", price="259.00"),
    ]
    result = analyze_trends(rows, CATALOG, RULES, seqn="batch-1")
    lowest = [event for event in result.events if event.rule_id is RuleId.LOWEST_COMPETITOR]
    lower = [event for event in result.events if event.rule_id is RuleId.COMPETITOR_PRICE_LOWER]
    assert len(lowest) == len(lower) == 2
    assert all(event.evidence["tie"] == "true" for event in lowest)
    assert lower[0].evidence["difference_amount"] == "50.00"
    assert lower[0].evidence["difference_percent"] == "20.08"


def test_stock_rules_only_compare_when_previous_batch_is_supplied() -> None:
    current = [target(stock="In Stock")]
    snapshot = analyze_trends(current, CATALOG, RULES, seqn="batch-1")
    compared = analyze_trends(
        current, CATALOG, RULES, seqn="batch-1", previous_rows=[target(stock="Out of Stock")]
    )
    assert snapshot.summary.snapshot_type == "current_snapshot"
    assert RuleId.STOCK_STATUS_CHANGED not in {event.rule_id for event in snapshot.events}
    assert {RuleId.STOCK_STATUS_CHANGED, RuleId.BACK_IN_STOCK} <= {
        event.rule_id for event in compared.events
    }


def test_out_of_stock_and_recurring_comment_evidence_are_traceable() -> None:
    product = CATALOG.products[0]
    result = analyze_trends(
        [target(stock="Out of Stock")],
        CATALOG,
        RULES,
        seqn="batch-1",
        comment_rows=[{"Product Name": product.product_name}],
        comment_evidence=[
            {
                "product_id": product.product_id,
                "negative_trend_detected": True,
                "recurring_issue_evidence": {"battery": ["review-1"]},
                "supporting_review_ids": ["review-1"],
            }
        ],
    )
    by_rule = {event.rule_id: event for event in result.events}
    assert RuleId.OUT_OF_STOCK in by_rule
    assert by_rule[RuleId.RECURRING_NEGATIVE_ISSUE].evidence["recurring_issue_evidence"] == {
        "battery": ["review-1"]
    }
    assert all(event.seqn == "batch-1" and event.severity for event in result.events)


def test_missing_comment_does_not_block_price_and_stock_analysis() -> None:
    result = analyze_trends([target()], CATALOG, RULES, seqn="batch-1")
    assert RuleId.COMPETITOR_PRICE_LOWER in {event.rule_id for event in result.events}
    assert result.summary.comment_row_count == 0


def test_missing_product_data_produces_explicit_warning() -> None:
    result = analyze_trends([target()], CATALOG, RULES, seqn="batch-1")
    assert {warning.product_id for warning in result.summary.warnings} == {
        "bose-quietcomfort-black",
        "sony-wh-1000xm5-black",
    }


def test_missing_final_price_produces_warning_without_guessing() -> None:
    raw = target().model_dump(mode="json", by_alias=True)
    raw["Final Price"] = None
    result = analyze_trends([raw], CATALOG, RULES, seqn="batch-1")
    assert any("Final Price" in warning.message for warning in result.summary.warnings)
    assert {event.rule_id for event in result.events} == {RuleId.INSUFFICIENT_DATA}


def test_mismatched_comment_evidence_seqn_is_rejected() -> None:
    with pytest.raises(ValueError, match="same SEQN"):
        analyze_trends(
            [target()],
            CATALOG,
            RULES,
            seqn="batch-1",
            comment_evidence=[{"seqn": "batch-2"}],
        )


def test_outputs_match_contract_and_json_csv_business_content(tmp_path: Path) -> None:
    result = analyze_trends(all_products(), CATALOG, RULES, seqn="batch-1")
    write_trend_outputs(result, tmp_path)
    assert len(result.rows) == 9
    json_rows = json.loads((tmp_path / "overall_trend.json").read_text(encoding="utf-8"))
    with (tmp_path / "overall_trend.csv").open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == sheet_headers(OverallTrendRow)
        csv_rows = list(reader)
    assert csv_rows == json_rows
    assert list(json_rows[0]) == sheet_headers(OverallTrendRow)
    assert {path.name for path in tmp_path.iterdir()} == {
        "overall_trend.json",
        "overall_trend.csv",
        "detected_events.json",
        "trend_summary.json",
    }


def test_fixed_inputs_are_deterministic_and_invalid_identity_is_rejected() -> None:
    assert (
        analyze_trends(all_products(), CATALOG, RULES, seqn="fixed").model_dump_json()
        == analyze_trends(all_products(), CATALOG, RULES, seqn="fixed").model_dump_json()
    )
    unknown = target().model_copy(update={"product_name": "Unknown"})
    with pytest.raises(ValueError, match="unknown product"):
        analyze_trends([unknown], CATALOG, RULES, seqn="fixed")
