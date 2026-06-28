"""Observability adapters — concrete ``ObservabilityPort`` implementations.

``phoenix/`` is the production backend (OpenInference traces → self-hosted Phoenix,
evals/datasets via the lightweight phoenix client). ``noop.py`` is the safe default
when observability is disabled. Swapping to another backend (e.g. Langfuse) means
adding a sibling package here and rebinding ``Container.observability``.
"""
