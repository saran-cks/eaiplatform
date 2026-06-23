"""AWS Bedrock LLM adapter implementing LLMPort.

Uses aioboto3 with the Bedrock Runtime ConverseStream API for SSE token streaming
and the Converse API for single-shot generation.

Mock-mode: if AWS_ACCESS_KEY_ID is unset the adapter falls back to a token
generator that simulates Claude-style streaming (useful for integration tests
without live Bedrock credentials).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence

from config.settings import Settings
from core.domain.entities.message import Message, Role

logger = logging.getLogger(__name__)

# Sentinel: if the key is empty we run in mock mode.
_MOCK_RESPONSE = (
    "I am a mock LLM response. "
    "Configure AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION "
    "in your .env file and enable Bedrock model access to receive real responses."
)


def _to_converse_messages(messages: Sequence[Message]) -> list[dict]:
    """Convert domain Message list to Bedrock Converse API format.

    Only USER and ASSISTANT roles are included; SYSTEM and TOOL messages are
    handled separately (system prompt) or skipped for phase 1.
    """
    converse = []
    for msg in messages:
        if msg.role in (Role.USER, Role.ASSISTANT):
            converse.append(
                {
                    "role": msg.role.value,
                    "content": [{"text": msg.content}],
                }
            )
    return converse


class BedrockAdapter:
    """LLMPort implementation via AWS Bedrock Converse/ConverseStream APIs."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._mock_mode = not bool(settings.aws_access_key_id)
        if self._mock_mode:
            logger.warning(
                "BedrockAdapter: AWS_ACCESS_KEY_ID is unset — running in MOCK mode. "
                "Real LLM calls are disabled."
            )
        else:
            logger.info(
                "BedrockAdapter initialised (region=%s, model=%s)",
                settings.aws_region,
                settings.bedrock_model_id,
            )

    # ------------------------------------------------------------------
    # Internal: aioboto3 session (lazily created, not cached — aioboto3
    # sessions are lightweight and should not be shared across threads).
    # ------------------------------------------------------------------
    def _make_boto_kwargs(self) -> dict:
        s = self._settings
        return {
            "region_name": s.aws_region,
            "aws_access_key_id": s.aws_access_key_id or None,
            "aws_secret_access_key": s.aws_secret_access_key or None,
            "aws_session_token": s.aws_session_token or None,
        }

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def generate(
        self,
        *,
        messages: Sequence[Message],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> str:
        """Single-shot text completion via Bedrock Converse API."""
        if self._mock_mode:
            return _MOCK_RESPONSE

        import aioboto3  # imported lazily to avoid import-time failures in mock mode

        s = self._settings
        model_id = model or s.bedrock_model_id
        inference_config: dict = {
            "maxTokens": max_tokens or s.bedrock_max_tokens,
            "temperature": temperature if temperature is not None else s.bedrock_temperature,
        }
        converse_messages = _to_converse_messages(messages)
        call_kwargs: dict = {
            "modelId": model_id,
            "messages": converse_messages,
            "inferenceConfig": inference_config,
        }
        if system:
            call_kwargs["system"] = [{"text": system}]

        session = aioboto3.Session(**self._make_boto_kwargs())
        async with session.client("bedrock-runtime") as client:
            response = await client.converse(**call_kwargs)

        # Extract text from the first content block of the output message
        output_message = response.get("output", {}).get("message", {})
        content_blocks = output_message.get("content", [])
        return "".join(block.get("text", "") for block in content_blocks if "text" in block)

    async def stream(
        self,
        *,
        messages: Sequence[Message],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        model: str | None = None,
    ) -> AsyncIterator[str]:
        """SSE token-delta stream via Bedrock ConverseStream API."""
        if self._mock_mode:
            async for chunk in _mock_stream():
                yield chunk
            return

        import aioboto3  # imported lazily

        s = self._settings
        model_id = model or s.bedrock_model_id
        inference_config: dict = {
            "maxTokens": max_tokens or s.bedrock_max_tokens,
            "temperature": temperature if temperature is not None else s.bedrock_temperature,
        }
        converse_messages = _to_converse_messages(messages)
        call_kwargs: dict = {
            "modelId": model_id,
            "messages": converse_messages,
            "inferenceConfig": inference_config,
        }
        if system:
            call_kwargs["system"] = [{"text": system}]

        session = aioboto3.Session(**self._make_boto_kwargs())
        async with session.client("bedrock-runtime") as client:
            response = await client.converse_stream(**call_kwargs)
            stream = response.get("stream")
            if stream is None:
                logger.error("ConverseStream returned no stream object")
                return

            async for event in stream:
                # Token delta from the model
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"].get("delta", {})
                    text = delta.get("text")
                    if text:
                        yield text
                # Stop reason signals end of stream; we just stop iterating
                elif "messageStop" in event:
                    break


async def _mock_stream() -> AsyncIterator[str]:
    """Yield _MOCK_RESPONSE word-by-word with a small delay to simulate streaming."""
    for word in _MOCK_RESPONSE.split():
        yield word + " "
        await asyncio.sleep(0.03)
