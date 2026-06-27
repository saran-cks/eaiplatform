"""Architecture invariant enforcement (hexagonal boundaries).

These tests fail the build if a layer imports something it must not. They are the
machine-checkable version of the dependency rule: *dependencies point inward only.*

    core           (domain, ports, use cases)  -- depends on NOTHING internal
      ^
    adapters / observability  (port implementations) -- may depend on core
      ^
    api / daemon   (delivery)  -- may depend on core, adapters, config
      ^
    config         (DI composition root) -- may depend on everything

Mechanism: static AST parsing, NOT importlib. We never execute the modules, so this
runs with zero third-party deps installed and cannot be fooled by runtime side effects.
A single accidental cross-layer import is caught here instead of rotting silently.
"""

from __future__ import annotations

import ast
from pathlib import Path

# src/  (this file lives at src/tests/test_architecture.py)
SRC_ROOT = Path(__file__).resolve().parent.parent

# Top-level packages that constitute our internal layers.
INTERNAL_PACKAGES = {
    "core",
    "adapters",
    "api",
    "config",
    "daemon",
    "observability",
}

# For each layer, the set of internal packages it is FORBIDDEN to import.
# Anything not listed (stdlib, third-party, or an allowed inner layer) is fine.
FORBIDDEN_IMPORTS: dict[str, set[str]] = {
    # The cardinal rule: the domain core is self-contained. It may never reach
    # outward into any adapter, the delivery layer, config, or wiring.
    "core": {"adapters", "api", "config", "daemon", "observability"},
    # Adapters implement ports; they must not depend on the delivery layer.
    "adapters": {"api", "daemon"},
    # Observability is a port implementation, same constraint as adapters.
    "observability": {"adapters", "api", "daemon", "config"},
}


def _layer_of(path: Path) -> str | None:
    """Return the top-level internal package a source file belongs to, if any."""
    rel = path.relative_to(SRC_ROOT)
    top = rel.parts[0]
    return top if top in INTERNAL_PACKAGES else None


def _imported_top_packages(tree: ast.AST) -> set[str]:
    """Collect the top-level package name of every import in a module."""
    tops: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                tops.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # Ignore relative imports (level > 0) — they never cross a top-level layer.
            if node.level == 0 and node.module:
                tops.add(node.module.split(".")[0])
    return tops


def _iter_source_files() -> list[Path]:
    files: list[Path] = []
    for pkg in INTERNAL_PACKAGES:
        pkg_dir = SRC_ROOT / pkg
        if pkg_dir.is_dir():
            files.extend(pkg_dir.rglob("*.py"))
    return files


def test_no_forbidden_cross_layer_imports():
    """Every source file obeys the inward-only dependency rule."""
    violations: list[str] = []

    for path in _iter_source_files():
        layer = _layer_of(path)
        if layer is None:
            continue
        forbidden = FORBIDDEN_IMPORTS.get(layer)
        if not forbidden:
            continue

        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for imported_top in _imported_top_packages(tree):
            if imported_top in forbidden:
                rel = path.relative_to(SRC_ROOT)
                violations.append(f"  {layer}: {rel} imports forbidden layer '{imported_top}'")

    assert not violations, (
        "Hexagonal architecture boundary violation(s) — dependencies must point inward:\n"
        + "\n".join(sorted(violations))
    )


def test_invariant_table_only_references_real_packages():
    """Guard against the rules drifting away from the actual source tree."""
    referenced = set(FORBIDDEN_IMPORTS) | {p for v in FORBIDDEN_IMPORTS.values() for p in v}
    assert referenced <= INTERNAL_PACKAGES
    for pkg in FORBIDDEN_IMPORTS:
        assert (SRC_ROOT / pkg).is_dir(), f"rule references missing package: {pkg}"
