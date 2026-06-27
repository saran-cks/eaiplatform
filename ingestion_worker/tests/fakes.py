"""In-memory fakes for every port, so the whole pipeline runs offline.

The fakes encode just enough behaviour to exercise the stages: the AV scanner flags an
EICAR-like marker, the content guard flags injection / abuse / PII by simple markers, and
the registry + sink record state for assertions.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ingestion_worker.domain.chunk import EmbeddedChunk
from ingestion_worker.domain.document import Document, RawItem, TextBlock
from ingestion_worker.ports.av_scanner import ScanResult
from ingestion_worker.ports.content_guard import (
    AbuseVerdict,
    InjectionVerdict,
    RedactionResult,
)
from ingestion_worker.ports.embedder import Embedding
from ingestion_worker.ports.registry import ChunkRecord

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


class FakeStaging:
    def __init__(self) -> None:
        self.staged: list[str] = []

    async def stage(self, item: RawItem) -> str:
        ref = f"s3://staging/{item.source}/{item.native_id}"
        self.staged.append(ref)
        return ref


class FakeAvScanner:
    async def scan(self, data: bytes) -> ScanResult:
        if b"EICAR" in data:
            return ScanResult(clean=False, signature="Eicar-Test-Signature")
        return ScanResult(clean=True)


class FakeParser:
    """Builds a Document from item.meta['blocks'] if present, else one body block."""

    async def parse(self, item: RawItem) -> Document:
        spec = item.meta.get("blocks")
        if spec:
            blocks = tuple(
                TextBlock(
                    text=b["text"],
                    field_role=b.get("field_role", "body"),
                    order=i,
                    is_table=b.get("is_table", False),
                )
                for i, b in enumerate(spec)  # type: ignore[arg-type]
            )
        else:
            blocks = (TextBlock(text=item.raw.decode("utf-8", "ignore"), field_role="body"),)
        return Document(
            source=item.source,
            native_id=item.native_id,
            tenant_id=item.tenant_id,
            source_type=item.source_type,
            permissions=item.permissions,
            blocks=blocks,
            lang=str(item.meta.get("lang", "")),
        )


class FakeContentGuard:
    async def screen_injection(self, text: str) -> InjectionVerdict:
        low = text.lower()
        risky = "ignore previous instructions" in low or "system prompt" in low
        return InjectionVerdict(injection_risk=0.97 if risky else 0.001)

    async def screen_abuse(self, text: str) -> AbuseVerdict:
        if "abuse_marker" in text.lower():
            return AbuseVerdict(unsafe=True, categories=("violence",))
        return AbuseVerdict(unsafe=False)

    async def redact_pii(self, text: str) -> RedactionResult:
        redacted, n = _EMAIL.subn("[REDACTED_EMAIL]", text)
        return RedactionResult(text=redacted, redacted=n > 0, entities=("EMAIL",) * n)


class FakeEmbedder:
    async def embed(self, texts: Sequence[str]) -> list[Embedding]:
        return [Embedding(dense=(float(len(t)), 1.0, 0.0, 0.0)) for t in texts]


class FakeRegistry:
    def __init__(self) -> None:
        self.hashes: dict[str, dict[str, str]] = {}        # document_id -> {chunk_id: hash}
        self.records: dict[str, ChunkRecord] = {}
        self.quarantines: list[dict[str, str | None]] = []

    async def get_doc_chunk_hashes(self, document_id: str) -> dict[str, str]:
        return dict(self.hashes.get(document_id, {}))

    async def record_chunks(self, records: Sequence[ChunkRecord]) -> None:
        for r in records:
            self.records[r.chunk_id] = r
            self.hashes.setdefault(r.document_id, {})[r.chunk_id] = r.content_hash

    async def delete_chunks(self, chunk_ids: Sequence[str]) -> None:
        for cid in chunk_ids:
            self.records.pop(cid, None)
            for doc in self.hashes.values():
                doc.pop(cid, None)

    async def record_quarantine(
        self, *, tenant_id, source, native_id, stage, reason
    ) -> None:
        self.quarantines.append(
            {"tenant_id": tenant_id, "source": source, "native_id": native_id,
             "stage": stage, "reason": reason}
        )


class FakeSink:
    def __init__(self) -> None:
        self.points: dict[str, EmbeddedChunk] = {}

    async def upsert(self, chunks: Sequence[EmbeddedChunk]) -> None:
        for ec in chunks:
            self.points[ec.chunk.chunk_id] = ec

    async def delete(self, chunk_ids: Sequence[str]) -> None:
        for cid in chunk_ids:
            self.points.pop(cid, None)
