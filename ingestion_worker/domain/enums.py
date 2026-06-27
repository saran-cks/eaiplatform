"""Source-type taxonomy that drives chunk-strategy routing."""

from __future__ import annotations

from enum import StrEnum


class SourceType(StrEnum):
    """How a document should be parsed and chunked. Mirrors the Chunk Strategy Router."""

    TEXT = "text"      # docx / txt / confluence / sharepoint prose
    CODE = "code"      # source files — chunk by function/class
    TICKET = "ticket"  # servicenow / zendesk — field-aware split
    PDF = "pdf"        # layout/section-aware, tables serialized separately
