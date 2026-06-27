"""Ingestion worker — a standalone, containerized deployable.

Completely decoupled from the core-api and the model sidecars: its only shared surface
is data at rest in Qdrant + Postgres (and spans in Phoenix). The schema of that shared
data is pinned in repo-root `contracts/` and cross-enforced by tests on both sides.

This package contains the worker's OWN domain models, ports, and pipeline stages. Real
adapters for the external systems (connectors, S3 staging, clamd, OCR, the embedder,
Qdrant/Postgres sinks) sit behind the ports in `ports/` and are wired separately.
"""
