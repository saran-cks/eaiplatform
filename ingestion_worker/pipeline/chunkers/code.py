"""Code chunker — keep each function/class intact as one chunk.

Phase-1 implementation is a lightweight regex splitter on top-level ``def``/``class``/
``function`` boundaries (covers Python/JS/TS/Java-ish shapes). A real AST/tree-sitter
adapter can replace this behind the same ChunkDraft output without touching callers.
"""

from __future__ import annotations

import re

from ingestion_worker.domain.document import Document
from ingestion_worker.pipeline.chunkers.base import ChunkDraft

# A top-level definition starts at column 0 with def/class/function (optionally async/export).
_DEF = re.compile(
    r"^(?:export\s+)?(?:async\s+)?(?:def|class|function)\s+([A-Za-z_][\w]*)",
    re.MULTILINE,
)


def chunk_code(document: Document) -> list[ChunkDraft]:
    drafts: list[ChunkDraft] = []
    seq = 0
    for block in document.blocks:
        src = block.text
        matches = list(_DEF.finditer(src))
        if not matches:
            # No recognizable units — keep the whole block intact (e.g. a config/script).
            if src.strip():
                drafts.append(ChunkDraft(text=src, field_role="module", seq=seq, meta=block.meta))
                seq += 1
            continue
        # Preamble before the first definition (imports, module docstring).
        if matches[0].start() > 0 and src[: matches[0].start()].strip():
            drafts.append(
                ChunkDraft(text=src[: matches[0].start()].rstrip(), field_role="module", seq=seq)
            )
            seq += 1
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(src)
            unit = src[m.start() : end].rstrip()
            if unit.strip():
                drafts.append(ChunkDraft(text=unit, field_role=f"def:{m.group(1)}", seq=seq))
                seq += 1
    return drafts
