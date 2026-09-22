"""Bounded one-time capture and deterministic fixture replay."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal, Protocol

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field

from competitive_intelligence.config import ProductCatalog
from competitive_intelligence.contracts import Vendor
from competitive_intelligence.fetching import (
    DirectHttpFetcher,
    FetchError,
    FetchMethod,
    FetchRequest,
    FetchResult,
    PageFetcher,
)
from competitive_intelligence.parsing import ParserRegistry, ProductObservation

DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RESPONSE_BYTES = 750_000
DEFAULT_RETRY_LIMIT = 1


class CaptureAdapter(Protocol):
    """Named fetcher in the provider-neutral fallback chain."""

    method: FetchMethod

    def fetch(self, request: FetchRequest) -> FetchResult: ...


class FixtureEntry(BaseModel):
    """Auditable metadata for one sanitized replay input."""

    model_config = ConfigDict(extra="forbid")

    product_id: str
    vendor: Vendor
    source_url: str
    captured_at: datetime
    capture_method: FetchMethod
    fixture_type: Literal["live", "synthetic"]
    evidence_path: str
    content_hash: Annotated[str, Field(pattern=r"^sha256:[0-9a-f]{64}$")]
    expected_output: ProductObservation


class FixtureManifest(BaseModel):
    """Versioned collection of replayable listings."""

    model_config = ConfigDict(extra="forbid")

    version: str
    fixtures: list[FixtureEntry]


class CaptureFailure(BaseModel):
    """Non-sensitive record proving that a listing failure was not hidden."""

    model_config = ConfigDict(extra="forbid")

    product_id: str
    vendor: Vendor
    source_url: str
    attempted_methods: list[FetchMethod]
    reasons: list[str]
    failed_at: datetime


def sanitize_html(html: str) -> str:
    """Retain parsing evidence while removing active and unrelated page content."""
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript", "iframe", "form", "img", "video"]):
        if node.name == "script" and node.get("type") == "application/ld+json":
            continue
        node.decompose()
    for node in soup.find_all(True):
        allowed = {"id", "class", "itemprop", "content", "property", "name", "aria-label"}
        node.attrs = {key: value for key, value in node.attrs.items() if key in allowed}
    return str(soup)


def sha256_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def load_manifest(path: Path) -> FixtureManifest:
    raw: object = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict) and isinstance(raw.get("fixtures"), list):
        vendor_names = {"Amazon": "amazon", "Walmart": "walmart", "Best Buy": "bestbuy"}
        for item in raw["fixtures"]:
            if not isinstance(item, dict):
                continue
            vendor = item.get("vendor")
            if isinstance(vendor, str):
                item["vendor"] = vendor_names.get(vendor, vendor)
            expected = item.get("expected_output")
            if isinstance(expected, dict):
                expected_vendor = expected.get("vendor")
                if isinstance(expected_vendor, str):
                    expected["vendor"] = vendor_names.get(expected_vendor, expected_vendor)
    return FixtureManifest.model_validate(raw)


def replay(manifest_path: Path, registry: ParserRegistry | None = None) -> list[ProductObservation]:
    """Replay local evidence only; no network-capable fetcher is constructed."""
    manifest = load_manifest(manifest_path)
    parser_registry = registry or ParserRegistry()
    root = manifest_path.parent
    observations: list[ProductObservation] = []
    for entry in manifest.fixtures:
        evidence_path = (root / entry.evidence_path).resolve()
        if root.resolve() not in evidence_path.parents:
            raise ValueError("fixture evidence path escapes the fixture directory")
        evidence = evidence_path.read_text(encoding="utf-8")
        if sha256_text(evidence) != entry.content_hash:
            raise ValueError(f"fixture hash mismatch: {entry.product_id}/{entry.vendor.value}")
        result = FetchResult(
            requested_url=entry.source_url,
            final_url=entry.source_url,
            status_code=200,
            html=evidence,
            method=FetchMethod.FIXTURE,
        )
        observation = parser_registry.get(entry.vendor).parse(
            result, product_id=entry.product_id, observed_at=entry.captured_at
        )
        if observation != entry.expected_output:
            raise ValueError(f"fixture output mismatch: {entry.product_id}/{entry.vendor.value}")
        observation.to_price_row(seqn="fixture-replay")
        observations.append(observation)
    return observations


def capture_live(
    catalog: ProductCatalog,
    output_dir: Path,
    adapters: Sequence[CaptureAdapter] | None = None,
    registry: ParserRegistry | None = None,
    *,
    retry_limit: int = DEFAULT_RETRY_LIMIT,
) -> tuple[list[ProductObservation], list[CaptureFailure]]:
    """Attempt every enabled listing independently and persist only sanitized evidence."""
    if retry_limit < 0:
        raise ValueError("retry_limit cannot be negative")
    selected: Sequence[CaptureAdapter] = adapters or (
        _DirectAdapter(),
        _UnavailableAdapter(FetchMethod.BROWSER),
        _UnavailableAdapter(FetchMethod.SCRAPING_API),
    )
    parser_registry = registry or ParserRegistry()
    output_dir.mkdir(parents=True, exist_ok=True)
    observations: list[ProductObservation] = []
    failures: list[CaptureFailure] = []
    for product in catalog.products:
        if not product.enabled:
            continue
        urls: Mapping[Vendor, str] = {
            Vendor.AMAZON: str(product.urls.amazon),
            Vendor.WALMART: str(product.urls.walmart),
            Vendor.BEST_BUY: str(product.urls.bestbuy),
        }
        for vendor, url in urls.items():
            reasons: list[str] = []
            methods: list[FetchMethod] = []
            captured: FetchResult | None = None
            for adapter in selected:
                methods.append(adapter.method)
                for _ in range(retry_limit + 1):
                    try:
                        captured = adapter.fetch(
                            FetchRequest(
                                url=url,
                                timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
                                max_response_bytes=DEFAULT_MAX_RESPONSE_BYTES,
                            )
                        )
                        break
                    except FetchError as exc:
                        reasons.append(f"{adapter.method.value}: {type(exc).__name__}: {exc}")
                if captured is not None:
                    break
            now = datetime.now(UTC)
            if captured is None:
                failures.append(
                    CaptureFailure(
                        product_id=product.product_id,
                        vendor=vendor,
                        source_url=url,
                        attempted_methods=methods,
                        reasons=reasons or ["no capture adapter configured"],
                        failed_at=now,
                    )
                )
                continue
            sanitized = sanitize_html(captured.html)
            path = output_dir / f"{product.product_id}--{vendor.value}.html"
            path.write_text(sanitized, encoding="utf-8")
            safe_result = FetchResult(
                requested_url=url,
                final_url=captured.final_url,
                status_code=captured.status_code,
                html=sanitized,
                method=captured.method,
            )
            observations.append(
                parser_registry.get(vendor).parse(
                    safe_result, product_id=product.product_id, observed_at=now
                )
            )
    (output_dir / "capture-failures.json").write_text(
        json.dumps([item.model_dump(mode="json") for item in failures], indent=2) + "\n",
        encoding="utf-8",
    )
    return observations, failures


class _DirectAdapter:
    method = FetchMethod.DIRECT_HTTP

    def __init__(self) -> None:
        self._fetcher: PageFetcher = DirectHttpFetcher()

    def fetch(self, request: FetchRequest) -> FetchResult:
        return self._fetcher.fetch(request)


class _UnavailableAdapter:
    """Explicitly record an optional adapter that has not been configured."""

    def __init__(self, method: FetchMethod) -> None:
        self.method = method

    def fetch(self, request: FetchRequest) -> FetchResult:
        del request
        raise FetchError(f"{self.method.value} adapter is not configured")
