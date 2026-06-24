"""Async gRPC server for the bge-m3 embedding sidecar.

Run from repo root:  python -m sidecars.model_server.server
"""
from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

import grpc

from .config import config
from .embedder import Embedder
from .proto import embedding_pb2 as pb
from .proto import embedding_pb2_grpc as pb_grpc

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("model_server")


class EmbeddingServicer(pb_grpc.EmbeddingServiceServicer):
    def __init__(self, embedder: Embedder, executor: ThreadPoolExecutor) -> None:
        self._embedder = embedder
        self._executor = executor
        # Bound concurrent inferences so we don't oversubscribe CPU cores.
        self._sem = asyncio.Semaphore(config.max_workers)

    async def GetEmbedding(
        self,
        request: pb.EmbeddingRequest,
        context: grpc.aio.ServicerContext,
    ) -> pb.EmbeddingResponse:
        if not request.text.strip():
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "text is required")

        loop = asyncio.get_running_loop()
        async with self._sem:
            # ONNX/torch inference releases the GIL → run off the event loop.
            dense, indices, values = await loop.run_in_executor(
                self._executor, self._embedder.encode, request.text
            )
        return pb.EmbeddingResponse(
            dense=dense,
            sparse=pb.SparseVector(indices=indices, values=values),
        )


async def serve() -> None:
    logger.info("Starting embedding sidecar…")
    embedder = Embedder()
    embedder.warmup()  # first request shouldn't pay the cold-start cost

    executor = ThreadPoolExecutor(
        max_workers=config.max_workers, thread_name_prefix="embed"
    )
    server = grpc.aio.server(maximum_concurrent_rpcs=config.max_workers * 8)
    pb_grpc.add_EmbeddingServiceServicer_to_server(
        EmbeddingServicer(embedder, executor), server
    )
    server.add_insecure_port(f"[::]:{config.grpc_port}")

    await server.start()
    logger.info(
        "Embedding sidecar listening on :%d (workers=%d, intra_op=%d)",
        config.grpc_port, config.max_workers, config.intra_op_threads,
    )
    try:
        await server.wait_for_termination()
    finally:
        executor.shutdown(wait=True)


if __name__ == "__main__":
    asyncio.run(serve())
