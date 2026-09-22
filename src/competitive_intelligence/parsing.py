"""Safe HTML evidence extraction and retailer-neutral parsing models."""

import json
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Annotated, Any, Protocol
from urllib.parse import urlparse

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field

from competitive_intelligence.contracts import PriceRow, StockStatus, Vendor
from competitive_intelligence.fetching import FetchResult


class UnsupportedRetailerError(ValueError):
    """The retailer or URL host is not supported by a parser."""


class ObservationConversionError(ValueError):
    """An incomplete observation cannot satisfy the Sheet contract."""


class ObservationStockStatus(StrEnum):
    """Observed stock state, including an honest unknown value."""

    IN_STOCK = "in_stock"
    OUT_OF_STOCK = "out_of_stock"
    UNKNOWN = "unknown"


class ExtractionMethod(StrEnum):
    """Highest-priority evidence source used by a parser."""

    JSON_LD = "json_ld"
    META = "meta"
    DOM = "dom"
    NONE = "none"


class ProductObservation(BaseModel):
    """One normalized, evidence-based retailer observation."""

    model_config = ConfigDict(extra="forbid")

    product_id: Annotated[str, Field(min_length=1)]
    product_name: str | None
    vendor: Vendor
    base_price: Annotated[Decimal | None, Field(ge=0)] = None
    final_price: Annotated[Decimal | None, Field(ge=0)] = None
    stock_status: ObservationStockStatus = ObservationStockStatus.UNKNOWN
    observed_at: datetime
    source_url: str
    extraction_method: ExtractionMethod
    warnings: list[str] = Field(default_factory=list)

    def to_price_row(self, seqn: str) -> PriceRow:
        """Convert only complete, contract-compatible evidence to a Sheet row."""
        missing: list[str] = []
        if self.product_name is None:
            missing.append("product_name")
        if self.final_price is None:
            missing.append("final_price")
        if self.stock_status is ObservationStockStatus.UNKNOWN:
            missing.append("stock_status")
        if missing:
            raise ObservationConversionError(
                f"observation cannot satisfy PriceRow; missing: {', '.join(missing)}"
            )
        assert self.product_name is not None
        assert self.final_price is not None
        sheet_stock = (
            StockStatus.IN_STOCK
            if self.stock_status is ObservationStockStatus.IN_STOCK
            else StockStatus.OUT_OF_STOCK
        )
        return PriceRow.model_validate(
            {
                "item_number": self.product_id,
                "product_name": self.product_name,
                "vendor": self.vendor,
                "base_price": self.base_price,
                "final_price": self.final_price,
                "stock_status": sheet_stock,
                "timestamp": self.observed_at.isoformat(),
                "seqn": seqn,
            }
        )


class RetailerParser(Protocol):
    """Replaceable parser boundary for one retailer."""

    vendor: Vendor

    def parse(
        self, result: FetchResult, *, product_id: str, observed_at: datetime
    ) -> ProductObservation:
        """Parse sanitized markup without executing embedded content."""


def clean_text(value: object) -> str | None:
    """Normalize whitespace and remove markup from a scalar evidence value."""
    if value is None:
        return None
    raw = str(value)
    text = BeautifulSoup(raw, "html.parser").get_text(" ", strip=True) if "<" in raw else raw
    normalized = " ".join(text.split())
    return normalized or None


def parse_price(value: object) -> Decimal | None:
    """Parse an explicitly observed non-negative decimal price."""
    text = clean_text(value)
    if text is None:
        return None
    match = re.search(r"(?:USD\s*)?\$?\s*([0-9]+(?:,[0-9]{3})*(?:\.[0-9]{1,2})?)", text)
    if match is None:
        return None
    try:
        price = Decimal(match.group(1).replace(",", ""))
    except InvalidOperation:
        return None
    return price if price >= 0 else None


def _json_ld_objects(soup: BeautifulSoup) -> list[dict[str, Any]]:
    objects: list[dict[str, Any]] = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            value: Any = json.loads(node.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        candidates = value if isinstance(value, list) else [value]
        for candidate in candidates:
            if isinstance(candidate, dict) and isinstance(candidate.get("@graph"), list):
                candidates.extend(candidate["@graph"])
            if isinstance(candidate, dict):
                objects.append(candidate)
    return objects


def _product_json_ld(soup: BeautifulSoup) -> dict[str, Any] | None:
    for value in _json_ld_objects(soup):
        kinds = value.get("@type")
        if kinds == "Product" or isinstance(kinds, list) and "Product" in kinds:
            return value
    return None


def _stock(value: object) -> ObservationStockStatus:
    text = (clean_text(value) or "").lower().replace("_", " ")
    if any(term in text for term in ("outofstock", "out of stock", "sold out", "unavailable")):
        return ObservationStockStatus.OUT_OF_STOCK
    if any(term in text for term in ("instock", "in stock", "available", "add to cart")):
        return ObservationStockStatus.IN_STOCK
    return ObservationStockStatus.UNKNOWN


class BaseRetailerParser:
    """Priority-ordered parser shared by retailer-specific selectors."""

    vendor: Vendor
    allowed_hosts: frozenset[str]
    name_selectors: tuple[str, ...]
    final_price_selectors: tuple[str, ...]
    base_price_selectors: tuple[str, ...]
    stock_selectors: tuple[str, ...]

    def parse(
        self, result: FetchResult, *, product_id: str, observed_at: datetime
    ) -> ProductObservation:
        host = (urlparse(result.final_url).hostname or "").lower()
        if host not in self.allowed_hosts:
            raise UnsupportedRetailerError(f"{self.vendor.value} parser rejects host: {host}")
        soup = BeautifulSoup(result.html, "html.parser")
        for unsafe in soup(["script", "style", "noscript", "iframe"]):
            if unsafe.get("type") != "application/ld+json":
                unsafe.decompose()

        name: str | None = None
        final_price: Decimal | None = None
        base_price: Decimal | None = None
        stock = ObservationStockStatus.UNKNOWN
        method = ExtractionMethod.NONE

        structured = _product_json_ld(soup)
        if structured is not None:
            name = clean_text(structured.get("name"))
            offers = structured.get("offers")
            if isinstance(offers, list):
                offers = next((offer for offer in offers if isinstance(offer, dict)), None)
            if isinstance(offers, dict):
                final_price = parse_price(offers.get("price"))
                base_price = parse_price(offers.get("highPrice"))
                stock = _stock(offers.get("availability"))
            if any((name, final_price, base_price, stock is not ObservationStockStatus.UNKNOWN)):
                method = ExtractionMethod.JSON_LD

        meta = {
            str(node.get("property") or node.get("name")): node.get("content")
            for node in soup.select("meta[property], meta[name]")
        }
        before_meta = (name, final_price, base_price, stock)
        name = name or clean_text(meta.get("og:title"))
        final_price = final_price or parse_price(
            meta.get("product:price:amount") or meta.get("og:price:amount")
        )
        base_price = base_price or parse_price(meta.get("product:original_price:amount"))
        if stock is ObservationStockStatus.UNKNOWN:
            stock = _stock(meta.get("product:availability"))
        if method is ExtractionMethod.NONE and before_meta != (
            name,
            final_price,
            base_price,
            stock,
        ):
            method = ExtractionMethod.META

        before_dom = (name, final_price, base_price, stock)
        name = name or self._text(soup, self.name_selectors)
        final_price = final_price or parse_price(self._text(soup, self.final_price_selectors))
        base_price = base_price or parse_price(self._text(soup, self.base_price_selectors))
        if stock is ObservationStockStatus.UNKNOWN:
            stock = _stock(self._text(soup, self.stock_selectors))
        if method is ExtractionMethod.NONE and before_dom != (name, final_price, base_price, stock):
            method = ExtractionMethod.DOM

        warnings: list[str] = []
        if name is None:
            warnings.append("product name not found")
        if final_price is None:
            warnings.append("final price not found")
        if base_price is None:
            warnings.append("base price not found")
        if stock is ObservationStockStatus.UNKNOWN:
            warnings.append("stock status could not be confirmed")
        return ProductObservation(
            product_id=product_id,
            product_name=name,
            vendor=self.vendor,
            base_price=base_price,
            final_price=final_price,
            stock_status=stock,
            observed_at=observed_at,
            source_url=result.final_url,
            extraction_method=method,
            warnings=warnings,
        )

    @staticmethod
    def _text(soup: BeautifulSoup, selectors: tuple[str, ...]) -> str | None:
        for selector in selectors:
            node = soup.select_one(selector)
            if node is not None:
                value = node.get("content") or node.get("aria-label") or node.get_text(" ")
                cleaned = clean_text(value)
                if cleaned is not None:
                    return cleaned
        return None


class AmazonParser(BaseRetailerParser):
    vendor = Vendor.AMAZON
    allowed_hosts = frozenset({"amazon.com", "www.amazon.com"})
    name_selectors = ("#productTitle", "#title")
    final_price_selectors = (
        ".priceToPay .a-offscreen",
        "#priceblock_ourprice",
        ".a-price .a-offscreen",
    )
    base_price_selectors = (".basisPrice .a-offscreen", ".a-text-price .a-offscreen")
    stock_selectors = ("#availability", "#add-to-cart-button")


class WalmartParser(BaseRetailerParser):
    vendor = Vendor.WALMART
    allowed_hosts = frozenset({"walmart.com", "www.walmart.com"})
    name_selectors = ('h1[itemprop="name"]', "h1")
    final_price_selectors = ('[itemprop="price"]', '[data-testid="price-wrap"]')
    base_price_selectors = ('[data-testid="list-price"]', ".strike-through")
    stock_selectors = ('[itemprop="availability"]', '[data-testid="add-to-cart-section"]')


class BestBuyParser(BaseRetailerParser):
    vendor = Vendor.BEST_BUY
    allowed_hosts = frozenset({"bestbuy.com", "www.bestbuy.com"})
    name_selectors = (".sku-title h1", 'h1[itemprop="name"]', "h1")
    final_price_selectors = (".priceView-customer-price span", '[itemprop="price"]')
    base_price_selectors = (".pricing-price__regular-price", ".priceView-price-match-guarantee")
    stock_selectors = (".fulfillment-add-to-cart-button", ".add-to-cart-button")


class ParserRegistry:
    """Resolve parsers without retailer conditionals in business logic."""

    def __init__(self, parsers: list[RetailerParser] | None = None) -> None:
        selected = parsers or [AmazonParser(), WalmartParser(), BestBuyParser()]
        self._parsers = {parser.vendor: parser for parser in selected}

    def get(self, vendor: Vendor) -> RetailerParser:
        try:
            return self._parsers[vendor]
        except KeyError as exc:
            raise UnsupportedRetailerError(f"unsupported retailer: {vendor}") from exc
