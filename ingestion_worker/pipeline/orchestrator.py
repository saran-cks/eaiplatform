"""IngestionPipeline — stitches the stages for one item, end to end.

Order (mirrors the design diagram):
    stage -> security gate -> parse/normalize -> content guard (abuse+PII) ->
    chunk router -> per-chunk injection screen -> enrich -> delta/dedup ->
    embed (new/changed) -> idempotent dual-write (Qdrant + registry).

Every external system is behind a port, so this whole class runs against fakes in unit
tests with no live services. A rejection at the security or content gate routes the item
to quarantine and stops — the file's chunks never reach Qdrant.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from dataclasses import replace

from ingestion_worker.domain.chunk import EmbeddedChunk
from ingestion_worker.domain.document import Document, RawItem
from ingestion_worker.pipeline.chunkers.router import route
from ingestion_worker.pipeline.dedup import diff
from ingestion_worker.pipeline.enrich import enrich
from ingestion_worker.pipeline.report import IngestReport, ItemResult
from ingestion_worker.pipeline.security_gate import SecurityGate
from ingestion_worker.ports.content_guard import ContentGuardPort
from ingestion_worker.ports.embedder import EmbedderPort
from ingestion_worker.ports.parser import ParserPort
from ingestion_worker.ports.registry import ChunkRecord, RegistryPort
from ingestion_worker.ports.sink import VectorSinkPort
from ingestion_worker.ports.staging import StagingPort

logger = logging.getLogger(__name__)


class IngestionPipeline:
    def __init__(
        self,
        *,
        staging: StagingPort,
        security_gate: SecurityGate,
        parser: ParserPort,
        content_guard: ContentGuardPort,
        embedder: EmbedderPort,
        registry: RegistryPort,
        sink: VectorSinkPort,
    ) -> None:
        self._staging = staging
        self._gate = security_gate
        self._parser = parser
        self._guard = content_guard
        self._embedder = embedder
        self._registry = registry
        self._sink = sink

    async def ingest_item(self, item: RawItem) -> ItemResult:
        # 1. immutable staging (replay/audit) — always, even for items we later reject.
        await self._staging.stage(item)

        # 2. security gate (magic-byte / size / clamd) BEFORE opening the file.
        gate = await self._gate.screen(item)
        if not gate.ok:
            await self._quarantine(item, stage="security_gate", reason=gate.reason or "rejected")
            return ItemResult(quarantined=True, reason=gate.reason)

        # 3. parse + normalize.
        document = await self._parser.parse(item)

        # 4. content guard: abuse (drop) + PII redaction, at block level.
        guarded = await self._guard_document(document)
        if guarded is None:
            await self._quarantine(item, stage="content_guard", reason="unsafe")
            return ItemResult(quarantined=True, reason="unsafe")
        document = guarded

        # 5. chunk by source type.
        drafts = route(document)
        if not drafts:
            return ItemResult(document_id=document.document_id)

        # 6. per-chunk injection screen -> the DD-13 signal stamped on every chunk.
        risks = [(await self._guard.screen_injection(d.text)).injection_risk for d in drafts]

        # 7. enrich -> contract-ready chunks.
        chunks = enrich(document, drafts, risks)

        # 8. delta/dedup vs the registry snapshot.
        prior = await self._registry.get_doc_chunk_hashes(document.document_id)
        plan = diff(chunks, prior)

        # 9-10. embed new/changed, then idempotent dual-write.
        if plan.to_upsert:
            embeddings = await self._embedder.embed([c.text for c in plan.to_upsert])
            embedded = [
                EmbeddedChunk(
                    chunk=c,
                    dense=e.dense,
                    sparse_indices=e.sparse_indices,
                    sparse_values=e.sparse_values,
                )
                for c, e in zip(plan.to_upsert, embeddings, strict=True)
            ]
            # Vectors first, then registry. chunk_id idempotency makes a retry after a
            # mid-write failure safe; a durable outbox/reconciliation is Phase-3 work.
            await self._sink.upsert(embedded)
            await self._registry.record_chunks(
                [
                    ChunkRecord(
                        chunk_id=c.chunk_id,
                        document_id=c.document_id,
                        tenant_id=c.tenant_id,
                        field_role=c.field_role,
                        seq=i,
                        content_hash=c.content_hash,
                        screened=c.screened,
                        injection_risk=c.injection_risk,
                    )
                    for i, c in enumerate(plan.to_upsert)
                ]
            )

        if plan.to_delete:
            await self._sink.delete(plan.to_delete)
            await self._registry.delete_chunks(plan.to_delete)

        return ItemResult(
            document_id=document.document_id,
            upserted=len(plan.to_upsert),
            unchanged=len(plan.unchanged),
            deleted=len(plan.to_delete),
        )

    async def ingest_batch(self, items: AsyncIterator[RawItem]) -> IngestReport:
        report = IngestReport()
        async for item in items:
            report.add(await self.ingest_item(item))
        return report

    # ------------------------------------------------------------------
    async def _guard_document(self, document: Document) -> Document | None:
        """Abuse-screen + PII-redact each block. Returns None if any block is unsafe."""
        new_blocks = []
        for block in document.blocks:
            abuse = await self._guard.screen_abuse(block.text)
            if abuse.unsafe:
                logger.warning(
                    "Content guard dropped unsafe doc %s (categories=%s)",
                    document.document_id, abuse.categories,
                )
                return None
            redaction = await self._guard.redact_pii(block.text)
            new_blocks.append(replace(block, text=redaction.text))
        return replace(document, blocks=tuple(new_blocks))

    async def _quarantine(self, item: RawItem, *, stage: str, reason: str) -> None:
        await self._registry.record_quarantine(
            tenant_id=item.tenant_id,
            source=item.source,
            native_id=item.native_id,
            stage=stage,
            reason=reason,
        )
