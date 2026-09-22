from datetime import UTC, datetime
from pathlib import Path

import pytest

from competitive_intelligence.capture import (
    CaptureAdapter,
    capture_live,
    load_manifest,
    replay,
    sanitize_html,
)
from competitive_intelligence.config import load_product_catalog
from competitive_intelligence.fetching import FetchError, FetchMethod, FetchRequest, FetchResult

ROOT = Path(__file__).parents[1]
MANIFEST = ROOT / "fixtures/product-pages/manifest.json"


def test_all_nine_fixtures_replay_deterministically() -> None:
    first = replay(MANIFEST)
    second = replay(MANIFEST)
    assert first == second
    assert len(first) == 9
    assert all(not observation.warnings for observation in first)


def test_manifest_tracks_three_products_and_retailers() -> None:
    manifest = load_manifest(MANIFEST)
    assert len(manifest.fixtures) == 9
    assert {entry.fixture_type for entry in manifest.fixtures} == {"synthetic"}
    assert len({(entry.product_id, entry.vendor) for entry in manifest.fixtures}) == 9


def test_hash_tampering_is_rejected(tmp_path: Path) -> None:
    manifest = load_manifest(MANIFEST)
    evidence = MANIFEST.parent / manifest.fixtures[0].evidence_path
    copied = tmp_path / evidence.name
    copied.write_text(evidence.read_text(encoding="utf-8") + "tampered", encoding="utf-8")
    changed = manifest.model_copy(deep=True)
    changed.fixtures = [changed.fixtures[0]]
    (tmp_path / "manifest.json").write_text(changed.model_dump_json(), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        replay(tmp_path / "manifest.json")


def test_sanitizer_removes_active_content_and_sensitive_attributes() -> None:
    cleaned = sanitize_html(
        '<html><script>alert(1)</script><div data-token="secret" id="price">$1</div></html>'
    )
    assert "alert" not in cleaned
    assert "secret" not in cleaned
    assert 'id="price"' in cleaned


class FailingAdapter:
    method = FetchMethod.DIRECT_HTTP

    def fetch(self, request: FetchRequest) -> FetchResult:
        raise FetchError(f"blocked: {request.url}")


def test_capture_continues_and_records_each_failure(tmp_path: Path) -> None:
    catalog = load_product_catalog(ROOT / "config/products.example.json")
    observations, failures = capture_live(
        catalog,
        tmp_path,
        adapters=[FailingAdapter()],
        retry_limit=0,
    )
    assert observations == []
    assert len(failures) == 9
    assert all(failure.reasons for failure in failures)
    assert (tmp_path / "capture-failures.json").is_file()


def test_capture_adapter_protocol_shape() -> None:
    adapter: CaptureAdapter = FailingAdapter()
    assert adapter.method is FetchMethod.DIRECT_HTTP
    assert datetime.now(UTC).tzinfo is not None
