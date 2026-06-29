"""Logging configuration tests.

Covers ``_configure_logging`` (api/main.py): stdout is always attached, and a file
handler is added — with its directory created — only when ``LOG_TO_FILE`` is true.
Root-logger state is snapshotted and restored so these tests don't leak handlers
into the rest of the suite (``basicConfig(force=True)`` mutates the root logger).
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from types import SimpleNamespace

from api.main import _configure_logging


@contextmanager
def _isolated_root():
    root = logging.getLogger()
    saved_handlers, saved_level = root.handlers[:], root.level
    try:
        yield
    finally:
        for h in root.handlers[:]:
            root.removeHandler(h)
        for h in saved_handlers:
            root.addHandler(h)
        root.setLevel(saved_level)


def _settings(tmp_path, *, log_to_file: bool):
    return SimpleNamespace(
        log_level="INFO",
        log_to_file=log_to_file,
        log_dir=str(tmp_path / "logs"),
        log_file="core-api.log",
    )


def test_stdout_only_when_log_to_file_false(tmp_path):
    with _isolated_root():
        _configure_logging(_settings(tmp_path, log_to_file=False))
        handlers = logging.getLogger().handlers
        assert any(isinstance(h, logging.StreamHandler) for h in handlers)
        assert not any(isinstance(h, logging.FileHandler) for h in handlers)
        assert not (tmp_path / "logs").exists()


def test_file_handler_added_and_dir_created_when_enabled(tmp_path):
    with _isolated_root():
        _configure_logging(_settings(tmp_path, log_to_file=True))
        handlers = logging.getLogger().handlers
        # FileHandler is a subclass of StreamHandler, so assert both are present distinctly.
        assert any(isinstance(h, logging.FileHandler) for h in handlers)
        assert (tmp_path / "logs" / "core-api.log").exists()
        for h in handlers:
            h.close()
