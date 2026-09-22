"""Versioned data contracts for the existing Google Sheet output."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

NonNegativePrice = Annotated[Decimal, Field(ge=0)]


def _validate_iso8601_timestamp(value: Any) -> Any:
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("Timestamp must be an ISO 8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Timestamp must include a timezone")
    return value


class Vendor(StrEnum):
    """Canonical retailer identifiers used by the project."""

    AMAZON = "amazon"
    WALMART = "walmart"
    BEST_BUY = "bestbuy"


VENDOR_ALIASES: dict[str, Vendor] = {
    "amazon": Vendor.AMAZON,
    "amazon.com": Vendor.AMAZON,
    "walmart": Vendor.WALMART,
    "walmart.com": Vendor.WALMART,
    "best buy": Vendor.BEST_BUY,
    "bestbuy": Vendor.BEST_BUY,
    "bestbuy.com": Vendor.BEST_BUY,
}


def normalize_vendor(value: object) -> Vendor:
    """Normalize a supported retailer name and reject unknown vendors."""
    if isinstance(value, Vendor):
        return value
    if not isinstance(value, str):
        raise ValueError("Vendor must be a string")
    key = " ".join(value.strip().lower().split())
    try:
        return VENDOR_ALIASES[key]
    except KeyError as exc:
        raise ValueError(f"Unsupported vendor: {value}") from exc


class StockStatus(StrEnum):
    """Stock values explicitly present in the existing workbook."""

    IN_STOCK = "In Stock"
    OUT_OF_STOCK = "Out of Stock"


class SheetRow(BaseModel):
    """Strict base model preserving case-sensitive Sheet headers as aliases."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)
    sheet_name: ClassVar[str]

    @field_validator("vendor", mode="before", check_fields=False)
    @classmethod
    def validate_vendor(cls, value: object) -> Vendor:
        return normalize_vendor(value)


class PriceRow(SheetRow):
    """STG/ODS price row contract."""

    sheet_name = "STG"

    item_number: Annotated[str, Field(alias="Item Number", min_length=1)]
    product_name: Annotated[str, Field(alias="Product Name", min_length=1)]
    vendor: Annotated[Vendor, Field(alias="Vendor")]
    base_price: Annotated[NonNegativePrice | None, Field(alias="Base Price")] = None
    final_price: Annotated[NonNegativePrice, Field(alias="Final Price")]
    stock_status: Annotated[StockStatus, Field(alias="Stock Status")]
    timestamp: Annotated[datetime, Field(alias="Timestamp")]
    seqn: Annotated[str, Field(alias="SEQN", min_length=1)]

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_iso_timestamp(cls, value: Any) -> Any:
        return _validate_iso8601_timestamp(value)


class TargetRow(SheetRow):
    """TGT comparison row contract."""

    sheet_name = "TGT"

    item_number: Annotated[str, Field(alias="Item Number", min_length=1)]
    product_name: Annotated[str, Field(alias="Product Name", min_length=1)]
    vendor: Annotated[Vendor, Field(alias="Vendor")]
    base_price: Annotated[NonNegativePrice | None, Field(alias="Base Price")] = None
    final_price: Annotated[NonNegativePrice, Field(alias="Final Price")]
    own_price: Annotated[NonNegativePrice, Field(alias="My price")]
    recent_stock: Annotated[StockStatus, Field(alias="Recent Stock")]
    current_stock: Annotated[StockStatus, Field(alias="Current Stock")]
    timestamp: Annotated[datetime, Field(alias="Timestamp")]

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_iso_timestamp(cls, value: Any) -> Any:
        return _validate_iso8601_timestamp(value)


class CommentRow(SheetRow):
    """Comment analysis row contract."""

    sheet_name = "Comment"

    product_name: Annotated[str, Field(alias="Product Name", min_length=1)]
    vendor: Annotated[Vendor, Field(alias="Vendor")]
    pros1: Annotated[str, Field(alias="Pros1")]
    pros2: Annotated[str, Field(alias="Pros2")]
    pros3: Annotated[str, Field(alias="Pros3")]
    cons1: Annotated[str, Field(alias="Cons1")]
    cons2: Annotated[str, Field(alias="Cons2")]
    cons3: Annotated[str, Field(alias="Cons3")]
    summary: Annotated[str, Field(alias="Summary")]


class OverallTrendRow(SheetRow):
    """Overall Trend row contract."""

    sheet_name = "Overall Trend"

    product_name: Annotated[str, Field(alias="Product Name", min_length=1)]
    vendor: Annotated[Vendor, Field(alias="Vendor")]
    overall_trend: Annotated[str, Field(alias="Overall Trend")]
    observation: Annotated[str, Field(alias="Observation")]


class RecentSuggestionRow(SheetRow):
    """Recent Suggestion row contract."""

    sheet_name = "Recent Suggestion"

    product_name: Annotated[str, Field(alias="Product Name", min_length=1)]
    vendor: Annotated[Vendor, Field(alias="Vendor")]
    suggestion: Annotated[str, Field(alias="Suggestion")]


SHEET_MODELS: dict[str, type[SheetRow]] = {
    "STG": PriceRow,
    "ODS": PriceRow,
    "TGT": TargetRow,
    "Comment": CommentRow,
    "Overall Trend": OverallTrendRow,
    "Recent Suggestion": RecentSuggestionRow,
}


def sheet_headers(model: type[SheetRow]) -> list[str]:
    """Return the exact case-sensitive Sheet aliases for a contract model."""
    return [field.alias or name for name, field in model.model_fields.items()]
