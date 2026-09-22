"""Provider-neutral page fetching contracts and a bounded HTTP adapter."""

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol, runtime_checkable
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class FetchError(RuntimeError):
    """Base error raised by page-fetching adapters."""


class FetchTimeoutError(FetchError):
    """The configured fetch deadline was exceeded."""


class ResponseTooLargeError(FetchError):
    """The response exceeded the configured byte limit."""


class FetchTransportError(FetchError):
    """The remote server or transport rejected the request."""


class FetchMethod(StrEnum):
    """How a page was obtained, without naming a provider."""

    DIRECT_HTTP = "direct_http"
    BROWSER = "browser"
    SCRAPING_API = "scraping_api"
    FIXTURE = "fixture"


@dataclass(frozen=True, slots=True)
class FetchRequest:
    """Safe, bounded request understood by every fetcher adapter."""

    url: str
    timeout_seconds: float = 10.0
    max_response_bytes: int = 1_000_000
    headers: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("url must be an absolute HTTP(S) URL")
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.max_response_bytes <= 0:
            raise ValueError("max_response_bytes must be positive")
        sensitive = {name.lower() for name in self.headers} & {"authorization", "cookie"}
        if sensitive:
            raise ValueError("persistent credentials and cookies are not accepted")


@dataclass(frozen=True, slots=True)
class FetchResult:
    """Fetched markup plus non-sensitive response metadata."""

    requested_url: str
    final_url: str
    status_code: int
    html: str
    method: FetchMethod
    content_type: str = "text/html"


@runtime_checkable
class PageFetcher(Protocol):
    """Replaceable boundary used by orchestration and business logic."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        """Return page markup or raise a typed ``FetchError``."""


class BrowserPageFetcher(PageFetcher, Protocol):
    """Boundary for a future browser-backed adapter."""


class ScrapingApiPageFetcher(PageFetcher, Protocol):
    """Boundary for a future hosted scraping adapter."""


class FixturePageFetcher(PageFetcher, Protocol):
    """Boundary for sanitized, offline fixture adapters."""


class DirectHttpFetcher:
    """Fetch HTML without executing JavaScript or retaining session state."""

    def fetch(self, request: FetchRequest) -> FetchResult:
        headers = {"User-Agent": "commerce-competitive-intelligence-demo/0.1", **request.headers}
        try:
            with urlopen(  # noqa: S310 - URL is explicitly supplied by the caller.
                Request(request.url, headers=headers), timeout=request.timeout_seconds
            ) as response:
                declared_size = response.headers.get("Content-Length")
                if declared_size:
                    try:
                        too_large = int(declared_size) > request.max_response_bytes
                    except ValueError as exc:
                        raise FetchTransportError("invalid Content-Length header") from exc
                    if too_large:
                        raise ResponseTooLargeError("response exceeds max_response_bytes")
                body = response.read(request.max_response_bytes + 1)
                if len(body) > request.max_response_bytes:
                    raise ResponseTooLargeError("response exceeds max_response_bytes")
                content_type = response.headers.get_content_type()
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    raise FetchTransportError(f"unsupported content type: {content_type}")
                charset = response.headers.get_content_charset() or "utf-8"
                return FetchResult(
                    requested_url=request.url,
                    final_url=response.geturl(),
                    status_code=response.status,
                    html=body.decode(charset, errors="replace"),
                    method=FetchMethod.DIRECT_HTTP,
                    content_type=content_type,
                )
        except TimeoutError as exc:
            raise FetchTimeoutError("page fetch timed out") from exc
        except HTTPError as exc:
            raise FetchTransportError(f"HTTP status {exc.code}") from exc
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise FetchTimeoutError("page fetch timed out") from exc
            raise FetchTransportError("page fetch failed") from exc


class LocalFixtureFetcher:
    """Read an explicitly mapped sanitized fixture without network access."""

    def __init__(self, fixtures: Mapping[str, Path]) -> None:
        self._fixtures = dict(fixtures)

    def fetch(self, request: FetchRequest) -> FetchResult:
        try:
            path = self._fixtures[request.url]
        except KeyError as exc:
            raise FetchTransportError("no fixture mapped for URL") from exc
        body = path.read_bytes()
        if len(body) > request.max_response_bytes:
            raise ResponseTooLargeError("fixture exceeds max_response_bytes")
        return FetchResult(
            requested_url=request.url,
            final_url=request.url,
            status_code=200,
            html=body.decode("utf-8", errors="replace"),
            method=FetchMethod.FIXTURE,
        )
