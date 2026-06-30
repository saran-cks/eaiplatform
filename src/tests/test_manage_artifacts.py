"""Unit tests for `ManageArtifactsUseCase` — agent artifact listing/retrieval.

Two things matter: every store read is **scoped to the caller's tenant** (an agent in
tenant A must never read tenant B's generated files), and the Monaco display hints
(language + MIME) are derived correctly from the file name, including the unknown-
extension fallback so the editor always gets a valid language id.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.use_cases.agent.manage_artifacts import ManageArtifactsUseCase


def _row(name: str, file_id: str = "f1", content: str = "x = 1") -> dict[str, object]:
    return {
        "file_id": file_id,
        "agent_session_id": "agent-1",
        "name": name,
        "content": content,
    }


# --- list_artifacts -------------------------------------------------------------------


async def test_list_maps_rows_and_passes_tenant_through():
    store = AsyncMock()
    store.list_artifacts.return_value = [_row("main.py"), _row("notes.md", file_id="f2")]
    use_case = ManageArtifactsUseCase(store)

    out = await use_case.list_artifacts(agent_session_id="agent-1", tenant_id="tenant-1")

    store.list_artifacts.assert_awaited_once_with(
        agent_session_id="agent-1", tenant_id="tenant-1"
    )
    assert [a["file_id"] for a in out] == ["f1", "f2"]
    assert out[0]["language"] == "python"
    assert out[0]["mime_type"] == "text/x-python"
    assert out[1]["language"] == "markdown"


async def test_list_empty_returns_empty_list():
    store = AsyncMock()
    store.list_artifacts.return_value = []
    use_case = ManageArtifactsUseCase(store)

    out = await use_case.list_artifacts(agent_session_id="agent-1", tenant_id="tenant-1")

    assert out == []


async def test_list_tolerates_missing_fields():
    """A row missing keys must still produce a fully-formed Monaco descriptor."""
    store = AsyncMock()
    store.list_artifacts.return_value = [{}]
    use_case = ManageArtifactsUseCase(store)

    out = await use_case.list_artifacts(agent_session_id="agent-1", tenant_id="tenant-1")

    assert out[0]["name"] == ""
    assert out[0]["language"] == "plaintext"
    assert out[0]["mime_type"] == "text/plain"


# --- get_artifact ---------------------------------------------------------------------


async def test_get_returns_none_when_not_found():
    store = AsyncMock()
    store.get_artifact.return_value = None
    use_case = ManageArtifactsUseCase(store)

    out = await use_case.get_artifact(file_id="missing", tenant_id="tenant-1")

    assert out is None
    store.get_artifact.assert_awaited_once_with(file_id="missing", tenant_id="tenant-1")


async def test_get_maps_row_with_display_hints():
    store = AsyncMock()
    store.get_artifact.return_value = _row("query.sql", file_id="f9", content="SELECT 1")
    use_case = ManageArtifactsUseCase(store)

    out = await use_case.get_artifact(file_id="f9", tenant_id="tenant-1")

    assert out is not None
    assert out["file_id"] == "f9"
    assert out["content"] == "SELECT 1"
    assert out["language"] == "sql"
    assert out["mime_type"] == "text/x-sql"


# --- display-hint derivation ----------------------------------------------------------


@pytest.mark.parametrize(
    "name,language,mime",
    [
        ("a.py", "python", "text/x-python"),
        ("a.json", "json", "application/json"),
        ("a.js", "javascript", "application/javascript"),
        ("a.ts", "typescript", "application/typescript"),
        ("a.sql", "sql", "text/x-sql"),
        ("a.html", "html", "text/html"),
        ("a.css", "css", "text/css"),
        ("a.sh", "shell", "text/x-shellscript"),
        ("a.md", "markdown", "text/markdown"),
        ("a.unknownext", "plaintext", "text/plain"),
        ("noextension", "plaintext", "text/plain"),
        ("Main.PY", "python", "text/x-python"),  # case-insensitive extension
    ],
)
async def test_display_hint_derivation(name: str, language: str, mime: str):
    store = AsyncMock()
    store.get_artifact.return_value = _row(name)
    use_case = ManageArtifactsUseCase(store)

    out = await use_case.get_artifact(file_id="f1", tenant_id="tenant-1")

    assert out is not None
    assert out["language"] == language
    assert out["mime_type"] == mime
