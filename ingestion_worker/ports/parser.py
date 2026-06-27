"""ParserPort — typed parse + normalize into the common Document model.

Real adapters handle docx/pdf(+OCR)/csv/code/json. They may need heavy/native deps
(Tesseract, Textract) and are built behind this port.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ingestion_worker.domain.document import Document, RawItem


@runtime_checkable
class ParserPort(Protocol):
    async def parse(self, item: RawItem) -> Document:
        """Extract typed content and normalize to a Document (blocks + meta)."""
        ...
