"""Validated product configuration loaded from committed JSON files."""

import json
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator


class RetailerUrls(BaseModel):
    """One configured URL for every supported retailer."""

    model_config = ConfigDict(extra="forbid")

    amazon: HttpUrl
    walmart: HttpUrl
    bestbuy: HttpUrl

    @field_validator("amazon")
    @classmethod
    def validate_amazon_host(cls, value: HttpUrl) -> HttpUrl:
        if value.host not in {"amazon.com", "www.amazon.com"}:
            raise ValueError("amazon URL must use amazon.com")
        return value

    @field_validator("walmart")
    @classmethod
    def validate_walmart_host(cls, value: HttpUrl) -> HttpUrl:
        if value.host not in {"walmart.com", "www.walmart.com"}:
            raise ValueError("walmart URL must use walmart.com")
        return value

    @field_validator("bestbuy")
    @classmethod
    def validate_bestbuy_host(cls, value: HttpUrl) -> HttpUrl:
        if value.host not in {"bestbuy.com", "www.bestbuy.com"}:
            raise ValueError("bestbuy URL must use bestbuy.com")
        return value


class ProductConfig(BaseModel):
    """Configuration for one product monitored by the Demo."""

    model_config = ConfigDict(extra="forbid")

    product_id: Annotated[str, Field(pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")]
    product_name: Annotated[str, Field(min_length=1)]
    own_price: Annotated[Decimal, Field(ge=0)]
    urls: RetailerUrls
    enabled: bool


class ProductCatalog(BaseModel):
    """Versioned collection of configured Demo products."""

    model_config = ConfigDict(extra="forbid")

    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    products: Annotated[list[ProductConfig], Field(min_length=1)]

    @model_validator(mode="after")
    def product_ids_are_unique(self) -> Self:
        product_ids = [product.product_id for product in self.products]
        if len(product_ids) != len(set(product_ids)):
            raise ValueError("product_id values must be unique")
        return self


def load_product_catalog(path: Path) -> ProductCatalog:
    """Load and validate a product catalog without any network access."""
    return ProductCatalog.model_validate_json(path.read_text(encoding="utf-8"))


def load_schema_manifest(path: Path) -> dict[str, object]:
    """Load the versioned Sheet schema manifest."""
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Schema manifest must be a JSON object")
    return value
