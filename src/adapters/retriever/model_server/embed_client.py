"""gRPC client for the bge-m3 embedding sidecar.

Sends query text and retrieves dense and sparse vector representations.
"""

from __future__ import annotations

import logging

import grpc

from adapters.retriever.model_server.proto.embedding_pb2 import EmbeddingRequest
from adapters.retriever.model_server.proto.embedding_pb2_grpc import EmbeddingServiceStub
from config.settings import Settings
from core.domain.value_objects.embedding_vector import EmbeddingVector, SparseVector

logger = logging.getLogger(__name__)


class ModelServerEmbedClient:
    """Async gRPC client for requesting text embeddings."""

    def __init__(self, settings: Settings) -> None:
        self._target = settings.model_server_target
        self._channel: grpc.aio.Channel | None = None
        self._stub: EmbeddingServiceStub | None = None
        logger.info("ModelServerEmbedClient initialized with target: %s", self._target)

    def _get_stub(self) -> EmbeddingServiceStub:
        if self._stub is None:
            self._channel = grpc.aio.insecure_channel(self._target)
            self._stub = EmbeddingServiceStub(self._channel)
        return self._stub

    async def embed(self, text: str) -> EmbeddingVector:
        stub = self._get_stub()
        try:
            request = EmbeddingRequest(text=text)
            # 5-second timeout on embedding generation
            response = await stub.GetEmbedding(request, timeout=5.0)

            dense = tuple(response.dense)
            sparse = None
            if response.HasField("sparse"):
                sparse = SparseVector(
                    indices=tuple(response.sparse.indices),
                    values=tuple(response.sparse.values),
                )

            return EmbeddingVector(
                dense=dense,
                sparse=sparse,
                model="bge-m3",
            )
        except Exception as e:
            logger.error("gRPC embed call failed for target %s: %s", self._target, e)
            raise

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
            self._stub = None
            logger.info("ModelServerEmbedClient channel closed.")
