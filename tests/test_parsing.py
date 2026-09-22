"""Offline tests for fetcher boundaries and retailer parsers."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from competitive_intelligence.contracts import Vendor
from competitive_intelligence.fetching import FetchMethod, FetchRequest, FetchResult
from competitive_intelligence.parsing import (
    AmazonParser,
    BestBuyParser,
    ExtractionMethod,
    ObservationConversionError,
    ObservationStockStatus,
    ParserRegistry,
    UnsupportedRetailerError,
    WalmartParser,
)

NOW = datetime(2026, 9, 22, 1, 0, tzinfo=UTC)


def result(url: str, html: str) -> FetchResult:
    return FetchResult(url, url, 200, html, FetchMethod.FIXTURE)


@pytest.mark.parametrize(
    ("parser", "url", "html", "vendor", "price"),
    [
        (
            AmazonParser(),
            "https://www.amazon.com/dp/demo",
            '<script type="application/ld+json">'
            '{"@type":"Product","name":"Headphones A","offers":'
            '{"price":"199.99","availability":"https://schema.org/InStock"}}'
            "</script>",
            Vendor.AMAZON,
            Decimal("199.99"),
        ),
        (
            WalmartParser(),
            "https://www.walmart.com/ip/demo",
            '<meta property="og:title" content="Headphones W">'
            '<meta property="product:price:amount" content="179.00">'
            '<meta property="product:availability" content="out of stock">',
            Vendor.WALMART,
            Decimal("179.00"),
        ),
        (
            BestBuyParser(),
            "https://www.bestbuy.com/site/demo",
            '<div class="sku-title"><h1>Headphones B</h1></div>'
            '<div class="priceView-customer-price"><span>$149.50</span></div>'
            '<button class="add-to-cart-button">Add to Cart</button>',
            Vendor.BEST_BUY,
            Decimal("149.50"),
        ),
    ],
)
def test_all_retailers_produce_standard_output(
    parser: AmazonParser | WalmartParser | BestBuyParser,
    url: str,
    html: str,
    vendor: Vendor,
    price: Decimal,
) -> None:
    observation = parser.parse(result(url, html), product_id="demo-product", observed_at=NOW)
    assert observation.vendor is vendor
    assert observation.final_price == price
    assert observation.product_name is not None
    assert observation.extraction_method is not ExtractionMethod.NONE


def test_missing_base_price_preserves_final_price_and_converts_to_contract() -> None:
    html = (
        '<meta property="og:title" content="Demo">'
        '<meta property="product:price:amount" content="99.00">'
        '<meta property="product:availability" content="in stock">'
    )
    observation = AmazonParser().parse(
        result("https://amazon.com/dp/demo", html), product_id="demo", observed_at=NOW
    )
    row = observation.to_price_row("run-1")
    assert row.base_price is None
    assert row.final_price == Decimal("99.00")


def test_unknown_stock_is_explicit_and_cannot_be_written_as_fact() -> None:
    observation = WalmartParser().parse(
        result("https://walmart.com/ip/demo", "<h1>Demo</h1><span itemprop='price'>$1</span>"),
        product_id="demo",
        observed_at=NOW,
    )
    assert observation.stock_status is ObservationStockStatus.UNKNOWN
    assert "stock status could not be confirmed" in observation.warnings
    with pytest.raises(ObservationConversionError):
        observation.to_price_row("run-1")


def test_wrong_domain_is_rejected() -> None:
    with pytest.raises(UnsupportedRetailerError):
        AmazonParser().parse(
            result("https://example.com/item", ""), product_id="x", observed_at=NOW
        )


def test_malformed_html_returns_warnings_instead_of_crashing() -> None:
    observation = BestBuyParser().parse(
        result("https://bestbuy.com/site/x", "<div><script>{broken</div>"),
        product_id="x",
        observed_at=NOW,
    )
    assert observation.extraction_method is ExtractionMethod.NONE
    assert observation.warnings


def test_registry_replaces_business_logic_branching() -> None:
    assert isinstance(ParserRegistry().get(Vendor.AMAZON), AmazonParser)


def test_fetch_request_rejects_unbounded_settings() -> None:
    with pytest.raises(ValueError):
        FetchRequest("https://example.com", timeout_seconds=0)
    with pytest.raises(ValueError):
        FetchRequest("file:///tmp/page.html")
    with pytest.raises(ValueError):
        FetchRequest("https://example.com", headers={"Cookie": "secret=value"})
