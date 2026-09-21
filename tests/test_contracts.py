"""Offline validation tests for Sheet and product contracts."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from competitive_intelligence.config import ProductCatalog, load_product_catalog
from competitive_intelligence.contracts import SHEET_MODELS, PriceRow, StockStatus, sheet_headers

ROOT = Path(__file__).parents[1]


def valid_price_row() -> dict[str, object]:
    return {
        "Item Number": "1",
        "Product Name": "Apple AirPods Pro 2",
        "Vendor": "Amazon.com",
        "Base Price": None,
        "Final Price": "249.00",
        "Stock Status": "In Stock",
        "Timestamp": "2026-09-21T12:30:00Z",
        "SEQN": "20260921123000",
    }


def test_manifest_matches_all_pydantic_contracts() -> None:
    manifest = json.loads((ROOT / "config/sheet-schema.v1.json").read_text(encoding="utf-8"))
    assert manifest["version"] == "1.0.0"
    assert list(manifest["sheets"]) == list(SHEET_MODELS)
    for sheet_name, model in SHEET_MODELS.items():
        assert manifest["sheets"][sheet_name] == sheet_headers(model)


def test_valid_price_row_normalizes_vendor_and_allows_null_base_price() -> None:
    row = PriceRow.model_validate(valid_price_row())
    assert row.vendor.value == "amazon"
    assert row.base_price is None
    assert row.stock_status is StockStatus.IN_STOCK


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("Vendor", "Other Shop"),
        ("Final Price", "-0.01"),
        ("Stock Status", "Available"),
        ("Timestamp", "2026-09-21 12:30:00"),
    ],
)
def test_invalid_price_values_are_rejected(field: str, value: str) -> None:
    data = valid_price_row()
    data[field] = value
    with pytest.raises(ValidationError):
        PriceRow.model_validate(data)


def test_case_sensitive_sheet_headers_are_enforced() -> None:
    data = valid_price_row()
    data["final price"] = data.pop("Final Price")
    with pytest.raises(ValidationError):
        PriceRow.model_validate(data)


def test_three_example_products_load_from_config() -> None:
    catalog = load_product_catalog(ROOT / "config/products.example.json")
    assert len(catalog.products) == 3
    assert {product.product_id for product in catalog.products} == {
        "apple-airpods-pro-2",
        "sony-wh-1000xm5-black",
        "bose-quietcomfort-black",
    }
    assert all(product.enabled for product in catalog.products)


def test_duplicate_product_ids_are_rejected() -> None:
    catalog_data = json.loads((ROOT / "config/products.example.json").read_text(encoding="utf-8"))
    catalog_data["products"].append(catalog_data["products"][0])
    with pytest.raises(ValidationError):
        ProductCatalog.model_validate(catalog_data)
