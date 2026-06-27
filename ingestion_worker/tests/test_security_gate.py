"""Security gate static-check tests — magic-byte + size guards (pre-parse).

These run before a file is ever opened, so they're the first security boundary. Only the
clamd path was exercised via the pipeline; the pure magic/size logic gets a direct test.
"""

from __future__ import annotations

from ingestion_worker.domain.document import RawItem
from ingestion_worker.domain.enums import SourceType
from ingestion_worker.pipeline.security_gate import static_checks


def _item(raw: bytes, content_type: str = "text/plain") -> RawItem:
    return RawItem(
        source="s", native_id="n", tenant_id="t1", source_type=SourceType.TEXT,
        permissions=frozenset(), content_type=content_type, raw=raw,
    )


def test_empty_payload_is_malformed():
    result = static_checks(_item(b""))
    assert not result.ok
    assert result.reason == "malformed"


def test_oversize_payload_rejected():
    result = static_checks(_item(b"x" * 50), max_bytes=10)
    assert not result.ok
    assert result.reason == "oversize"


def test_magic_byte_mismatch_rejected():
    # Declares PDF but the bytes don't start with %PDF -> trust the bytes, not the label.
    result = static_checks(_item(b"not a pdf", content_type="application/pdf"))
    assert not result.ok
    assert result.reason == "malformed"


def test_valid_pdf_magic_passes():
    assert static_checks(_item(b"%PDF-1.7 ...", content_type="application/pdf")).ok


def test_text_type_without_magic_passes():
    assert static_checks(_item(b"plain text has no magic")).ok
