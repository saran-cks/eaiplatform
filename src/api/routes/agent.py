"""Agent API routes.

Endpoints:
  POST /agent/{session_id}/run       — Triggers the agent loop; streams progress via SSE.
  POST /agent/{agent_session_id}/interrupt — Cooperative cancellation trigger.
  GET  /agent/{agent_session_id}/artifacts — List code artifacts generated during the run.
  GET  /agent/artifacts/{file_id}     — Retrieve specific code file artifact by ID.
"""

from __future__ import annotations

import json
import logging
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from api.schemas.agent import (
    AgentRunRequest,
    ArtifactOut,
)
from core.use_cases.agent.interrupt_agent import InterruptAgentUseCase
from core.use_cases.agent.manage_artifacts import ManageArtifactsUseCase
from core.use_cases.agent.run_agent import RunAgentUseCase

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


def _get_scope(request: Request):  # type: ignore[return]
    """Extract PermissionScope from request state, raise 401 if absent."""
    scope = getattr(request.state, "scope", None)
    if scope is None:
        raise HTTPException(status_code=401, detail="Permission scope missing from request context")
    return scope


# ---------------------------------------------------------------------------
# POST /agent/{session_id}/run — SSE streaming agent loop
# ---------------------------------------------------------------------------
@router.post(
    "/{session_id}/run",
    summary="Trigger the diagnostic agent and stream status/thoughts (SSE)",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-Sent Events stream of task/thought events ending with done",
            "content": {"text/event-stream": {}},
        }
    },
)
async def run_agent(
    session_id: str,
    body: AgentRunRequest,
    request: Request,
) -> StreamingResponse:
    """Stream agent thought process and tool execution logs via SSE.

    Events emitted:
      event: thought       - Planner/Synthesizer reasoning content.
      event: worker_start  - Notification of parallel task execution starting.
      event: worker_done   - Notification of parallel task execution finishing.
      event: synthesis     - Correlation reasoning start.
      event: output        - Final synthesized Markdown answer tokens.
      event: error         - Task failure descriptions.
      event: done          - Loop termination marker.

    Handles client disconnects by calling agent_port.interrupt().
    """
    scope = _get_scope(request)
    container = request.app.state.container

    # Generate a unique session ID for the running instance
    agent_session_id = str(uuid4())

    run_uc = RunAgentUseCase(store=container.store, agent=container.agent, guard=container.guard)

    async def _event_generator():
        truncated = False
        try:
            pipeline = await run_uc.execute(
                session_id=session_id,
                agent_session_id=agent_session_id,
                prompt=body.prompt,
                scope=scope,
            )
            async for step in pipeline:
                event_name = step.get("event", "output")
                payload = step.get("data", {})
                
                # Check for truncated indicator at termination done event
                if event_name == "done":
                    truncated = payload.get("truncated", False)
                elif event_name == "output":
                    truncated = payload.get("truncated", False)
                
                # Render EventSource-compliant frame
                # escape newlines for data lines to keep SSE framing valid
                data_json = json.dumps(payload)
                yield f"event: {event_name}\ndata: {data_json}\n\n"

        except GeneratorExit:
            logger.warning("SSE client disconnected for agent run %s", agent_session_id)
            # Cooperative cancel of the graph runner task
            await container.agent.interrupt(agent_session_id=agent_session_id)
        except Exception as exc:
            logger.exception("SSE agent pipeline error: %s", exc)
            err_payload = json.dumps(
                {
                    "message": "An internal error occurred during agent execution.",
                    "source": "orchestrator",
                }
            )
            yield f"event: error\ndata: {err_payload}\n\n"
        finally:
            done_payload = json.dumps({"session_id": agent_session_id, "truncated": truncated})
            yield f"event: done\ndata: {done_payload}\n\n"

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable proxy buffering
        },
    )


# ---------------------------------------------------------------------------
# POST /agent/{agent_session_id}/interrupt — Cooperative cancel
# ---------------------------------------------------------------------------
@router.post(
    "/{agent_session_id}/interrupt",
    summary="Interrupt a running agent task cooperatively",
)
async def interrupt_agent(agent_session_id: str, request: Request) -> dict[str, str]:
    """Flag the agent runner task to stop execution.

    Auth alone is insufficient here: the cooperative-cancel signal keys purely off the
    session id, so the use case must confirm the caller's tenant owns the session before
    dispatching — otherwise any authenticated user could cancel any tenant's agent (a
    cross-tenant DoS). A session the caller's tenant doesn't own is reported as 404.
    """
    scope = _get_scope(request)
    container = request.app.state.container

    interrupt_uc = InterruptAgentUseCase(store=container.store, agent=container.agent)
    try:
        interrupted = await interrupt_uc.execute(
            agent_session_id=agent_session_id, scope=scope
        )
    except Exception as exc:
        logger.error("Failed to interrupt agent task: %s", exc)
        raise HTTPException(
            status_code=500, detail="Failed to interrupt agent execution"
        ) from exc

    if not interrupted:
        raise HTTPException(status_code=404, detail="Agent session not found")

    return {"status": "interrupted"}


# ---------------------------------------------------------------------------
# GET /agent/{agent_session_id}/artifacts — List code files
# ---------------------------------------------------------------------------
@router.get(
    "/{agent_session_id}/artifacts",
    response_model=list[ArtifactOut],
    summary="List code artifacts generated during the agent run",
)
async def list_artifacts(agent_session_id: str, request: Request) -> list[ArtifactOut]:
    """Return Monaco-editor-ready metadata for files produced by the agent."""
    scope = _get_scope(request)
    container = request.app.state.container

    manage = ManageArtifactsUseCase(store=container.store)
    results = await manage.list_artifacts(
        agent_session_id=agent_session_id,
        tenant_id=scope.tenant_id,
    )
    return [
        ArtifactOut(
            file_id=r["file_id"],
            name=r["name"],
            content=r["content"],
            language=r["language"],
            mime_type=r["mime_type"],
        )
        for r in results
    ]


# ---------------------------------------------------------------------------
# GET /agent/artifacts/{file_id} — Fetch single file
# ---------------------------------------------------------------------------
@router.get(
    "/artifacts/{file_id}",
    response_model=ArtifactOut,
    summary="Retrieve a specific generated code file by ID",
)
async def get_artifact(file_id: str, request: Request) -> ArtifactOut:
    """Return the name, code content, and parser language for a single file."""
    scope = _get_scope(request)
    container = request.app.state.container

    manage = ManageArtifactsUseCase(store=container.store)
    r = await manage.get_artifact(file_id=file_id, tenant_id=scope.tenant_id)
    if not r:
        raise HTTPException(status_code=404, detail="Artifact not found")

    return ArtifactOut(
        file_id=r["file_id"],
        name=r["name"],
        content=r["content"],
        language=r["language"],
        mime_type=r["mime_type"],
    )
