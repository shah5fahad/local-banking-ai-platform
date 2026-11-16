"""Chat and SSE streaming endpoints for AI assistant."""
from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy.orm import Session, sessionmaker

from app.agents.graph import get_graph
from app.agents.guards.input_guard import sanitise_message
from app.core.config import AISettings, get_settings
from app.core.errors import NotFoundError, UnauthorizedError
from app.core.security import decode_banking_jwt, extract_roles, extract_session_id, extract_user_id
from app.db.engine import get_session_factory
from app.db.session import get_db
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.approval import (
    ApprovalResponse,
    DecisionRequest,
    DecisionResponse,
    PruneCheckpointsRequest,
    PruneCheckpointsResponse,
    ResumeRequest,
    ResumeResponse,
    SweepResponse,
)
from app.schemas.chat import ChatRequest
from app.services.approval_service import ApprovalService
from app.services.expiry_sweeper import ExpirySweeperService

logger = logging.getLogger(__name__)

bearer_auth = HTTPBearer(auto_error=False)

router = APIRouter(prefix="/chat", tags=["chat"])


def get_current_user_and_token(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_auth),
    settings: AISettings = Depends(get_settings),
) -> tuple[dict, str]:
    """Validate JWT and extract claims and raw token."""
    if not credentials:
        raise UnauthorizedError("Authentication token required")
    payload = decode_banking_jwt(credentials.credentials, settings)
    return payload, credentials.credentials


UserAuth = Annotated[tuple[dict, str], Depends(get_current_user_and_token)]
DbSession = Annotated[Session, Depends(get_db)]
AppSettings = Annotated[AISettings, Depends(get_settings)]


@router.post("/messages", summary="Send chat message and receive SSE stream")
async def send_message(
    body: ChatRequest,
    user_auth: UserAuth,
    db: DbSession,
    settings: AppSettings,
    request: Request,
    session_factory: sessionmaker[Session] = Depends(get_session_factory),
) -> StreamingResponse:
    """Send message to assistant and stream SSE events (status, tool, token, citations, done)."""
    payload, raw_token = user_auth
    user_id = extract_user_id(payload)
    roles = extract_roles(payload)
    role_snapshot = roles[0] if roles else "CUSTOMER"
    session_id = extract_session_id(payload) or ""

    repo = ConversationRepository(db)
    user_ref = repo.get_or_create_user_ref(
        banking_user_id=user_id,
        role_snapshot=role_snapshot,
        display_name_masked=f"User {user_id[-4:] if len(user_id) >= 4 else user_id}",
    )

    if body.conversation_id:
        conversation = repo.get_conversation(body.conversation_id, user_ref.id)
        if not conversation:
            raise NotFoundError("Conversation", body.conversation_id)
    else:
        title = body.message[:50].strip()
        conversation = repo.create_conversation(user_ref.id, title=title)

    # Persist user message
    user_msg = repo.add_message(
        conversation_id=conversation.id,
        role="user",
        content_masked=sanitise_message(body.message),
    )
    db.commit()
    db.refresh(conversation)

    conv_id = conversation.id
    user_msg_id = user_msg.id
    raw_message = body.message

    async def sse_generator() -> AsyncGenerator[str, None]:
        worker_db: Session = session_factory()
        worker_repo = ConversationRepository(worker_db)
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))

        try:
            # 1. Yield initial status
            yield (
                "event: status\ndata: "
                f"{json.dumps({'status': 'processing', 'node': 'input_guard'})}\n\n"
            )

            # 2. Prepare LangGraph inputs
            history_rows = worker_repo.list_messages(conv_id, page=1, page_size=20)
            langchain_messages: list[Any] = []
            for h in history_rows:
                if h.role == "user":
                    langchain_messages.append(HumanMessage(content=h.content_masked))
                elif h.role == "assistant":
                    langchain_messages.append(AIMessage(content=h.content_masked))

            state_input: dict[str, Any] = {
                "user_id": user_id,
                "session_id": session_id,
                "conversation_id": conv_id,
                "request_id": request_id,
                "user_message": raw_message,
                "messages": langchain_messages,
                "tool_results": [],
                "approval_status": "NONE",
                "authentication_status": "NONE",
                "response": None,
                "citations": None,
                "input_blocked": False,
                "input_block_reason": None,
                "agent_route": None,
                "intent": None,
                "error_code": None,
                "transaction_reference": None,
            }
            config = {
                "configurable": {
                    "thread_id": conv_id,
                    "access_token": raw_token,
                }
            }

            graph = get_graph()
            final_state: dict[str, Any] = {}
            start_time = time.time()

            # Stream nodes execution
            is_interrupted = False
            interrupt_payload: dict[str, Any] = {}

            for step in graph.stream(state_input, config=config, stream_mode="updates"):
                for node_name, node_update in step.items():
                    if node_name == "__interrupt__":
                        is_interrupted = True
                        interrupt_tuple = (
                            node_update if isinstance(node_update, (list, tuple)) else [node_update]
                        )
                        interrupt_obj = interrupt_tuple[0] if interrupt_tuple else {}
                        interrupt_val = getattr(interrupt_obj, "value", interrupt_obj)
                        if isinstance(interrupt_val, dict):
                            interrupt_payload = interrupt_val
                        logger.info("Graph execution interrupted with: %s", interrupt_val)
                        yield f"event: approval_required\ndata: {json.dumps(interrupt_val)}\n\n"
                        break

                    latency = int((time.time() - start_time) * 1000)
                    start_time = time.time()

                    # Trace execution in agent_execution table
                    tool_res_list = (
                        node_update.get("tool_results") or []
                        if isinstance(node_update, dict)
                        else []
                    )
                    tool_name = tool_res_list[0].get("tool_name") if tool_res_list else None
                    if isinstance(node_update, dict):
                        worker_repo.log_execution(
                            conversation_id=conv_id,
                            message_id=user_msg_id,
                            node=node_name,
                            route=node_update.get("agent_route"),
                            tool_name=tool_name,
                            tool_args_masked=None,
                            status="SUCCESS" if not node_update.get("error_code") else "ERROR",
                            latency_ms=latency,
                            error_code=node_update.get("error_code"),
                            request_id=request_id,
                        )
                        worker_db.commit()

                    # SSE updates
                    if isinstance(node_update, dict):
                        if node_name == "supervisor":
                            supervisor_status = {
                                "status": "classified",
                                "intent": node_update.get("intent"),
                                "route": node_update.get("agent_route"),
                            }
                            yield f"event: status\ndata: {json.dumps(supervisor_status)}\n\n"
                        elif node_name == "banking_ops":
                            for t in tool_res_list:
                                tool_evt = {
                                    "tool": t.get("tool_name"),
                                    "success": t.get("success", True),
                                }
                                yield f"event: tool\ndata: {json.dumps(tool_evt)}\n\n"
                        elif node_name in ("policy_rag", "external_research"):
                            yield (
                                "event: status\ndata: "
                                f"{json.dumps({'status': 'researching', 'node': node_name})}\n\n"
                            )
                        elif node_update.get("pending_action"):
                            pa_json = json.dumps(node_update["pending_action"])
                            yield f"event: approval_required\ndata: {pa_json}\n\n"

                        final_state.update(node_update)

                if is_interrupted:
                    break

            if is_interrupted:
                approval_id = interrupt_payload.get("approval_id")
                wf_name = str(interrupt_payload.get("workflow", "transaction")).lower()
                asst_text = (
                    f"A {wf_name} request requires your confirmation. "
                    "Please review the details above and confirm or reject to proceed."
                )
                asst_msg = worker_repo.add_message(
                    conversation_id=conv_id,
                    role="assistant",
                    content_masked=asst_text,
                )
                worker_db.commit()
                yield f"event: token\ndata: {json.dumps({'token': asst_text})}\n\n"
                done_payload = {
                    "conversation_id": conv_id,
                    "message_id": asst_msg.id,
                    "status": "INTERRUPTED",
                    "approval_id": approval_id,
                }
                yield f"event: done\ndata: {json.dumps(done_payload)}\n\n"
                return

            # 3. Final response & citations
            response_text = final_state.get("response") or "I processed your request."
            citations = final_state.get("citations") or []

            if citations:
                yield f"event: citations\ndata: {json.dumps({'citations': citations})}\n\n"

            # 4. Stream response tokens
            yield f"event: token\ndata: {json.dumps({'token': response_text})}\n\n"

            # 5. Persist assistant message
            asst_msg = worker_repo.add_message(
                conversation_id=conv_id,
                role="assistant",
                content_masked=response_text,
                citations_json=json.dumps(citations) if citations else None,
            )
            worker_db.commit()

            # 6. Yield done event
            done_info = {
                "conversation_id": conv_id,
                "message_id": asst_msg.id,
                "response": response_text,
            }
            yield f"event: done\ndata: {json.dumps(done_info)}\n\n"

        except Exception as exc:
            logger.exception("Error in chat streaming: %s", exc)
            err_data = json.dumps({"error": "INTERNAL_ERROR", "message": str(exc)})
            yield f"event: error\ndata: {err_data}\n\n"
        finally:
            worker_db.close()

    return StreamingResponse(
        sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/approvals/active",
    summary="Get active pending approval for conversation",
    response_model=ApprovalResponse | None,
)
def get_active_approval(
    conversation_id: str,
    user_auth: UserAuth,
    db: DbSession,
    settings: AppSettings,
    workflow_type: str | None = None,
) -> dict[str, Any] | None:
    """Retrieve currently active pending approval in a conversation, if any."""
    payload, _ = user_auth
    user_id = extract_user_id(payload)
    service = ApprovalService(db, settings=settings)
    approval = service.get_active_approval_for_conversation(
        conversation_id=conversation_id,
        workflow_type=workflow_type,
        banking_user_id=user_id,
    )
    if not approval:
        return None
    return {
        "approval_id": approval.id,
        "conversation_id": approval.conversation_id,
        "workflow": approval.workflow_type,
        "risk_level": approval.risk_level,
        "status": approval.status,
        "summary": approval.summary_masked,
        "summary_hash": approval.summary_hash,
        "banking_resource_id": approval.banking_resource_id,
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
    }


@router.post(
    "/approvals/sweep",
    summary="Manually trigger HITL approval expiry sweep",
    response_model=SweepResponse,
)
def sweep_approvals(
    user_auth: UserAuth,
    db: DbSession,
    settings: AppSettings,
) -> dict[str, Any]:
    """Sweep expired approvals, cancel banking drafts, and update status."""
    _, raw_token = user_auth
    sweeper = ExpirySweeperService(db, settings=settings)
    results = sweeper.sweep_expired_approvals(raw_token=raw_token)
    return {
        "swept_count": len(results),
        "swept_approvals": [r["approval_id"] for r in results],
        "details": results,
    }


@router.get(
    "/approvals/{approval_id}",
    summary="Get pending approval state",
    response_model=ApprovalResponse,
)
def get_approval(
    approval_id: str,
    user_auth: UserAuth,
    db: DbSession,
    settings: AppSettings,
) -> dict[str, Any]:
    """Retrieve details and status of a pending HITL approval."""
    payload, _ = user_auth
    user_id = extract_user_id(payload)
    service = ApprovalService(db, settings=settings)
    approval = service.get_approval(approval_id, banking_user_id=user_id)

    return {
        "approval_id": approval.id,
        "conversation_id": approval.conversation_id,
        "workflow": approval.workflow_type,
        "risk_level": approval.risk_level,
        "status": approval.status,
        "summary": approval.summary_masked,
        "summary_hash": approval.summary_hash,
        "banking_resource_id": approval.banking_resource_id,
        "expires_at": approval.expires_at.isoformat() if approval.expires_at else None,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
    }


@router.post(
    "/approvals/{approval_id}/decision",
    summary="Confirm or reject pending approval",
    response_model=DecisionResponse,
)
def decide_approval(
    approval_id: str,
    body: DecisionRequest,
    user_auth: UserAuth,
    db: DbSession,
    settings: AppSettings,
) -> dict[str, Any]:
    """Submit human decision (CONFIRM/REJECT) for a pending approval."""
    payload, raw_token = user_auth
    user_id = extract_user_id(payload)
    service = ApprovalService(db, settings=settings)
    return service.decide_approval(
        approval_id=approval_id,
        decision=body.decision,
        banking_user_id=user_id,
        raw_token=raw_token,
    )


@router.post(
    "/approvals/{approval_id}/resume",
    summary="Resume approval after banking PIN/OTP",
    response_model=ResumeResponse,
)
def resume_approval(
    approval_id: str,
    body: ResumeRequest,
    user_auth: UserAuth,
    db: DbSession,
    settings: AppSettings,
) -> dict[str, Any]:
    """Resume transaction execution after user completed PIN verification directly at banking."""
    payload, raw_token = user_auth
    user_id = extract_user_id(payload)
    service = ApprovalService(db, settings=settings)
    return service.resume_approval(
        approval_id=approval_id,
        authorization_id=body.authorization_id,
        banking_user_id=user_id,
        raw_token=raw_token,
        summary_hash=body.summary_hash,
    )


@router.post(
    "/checkpoints/prune",
    summary="Prune old/terminal checkpoints and metadata",
    response_model=PruneCheckpointsResponse,
)
def prune_checkpoints(
    user_auth: UserAuth,
    db: DbSession,
    settings: AppSettings,
    body: PruneCheckpointsRequest | None = None,
) -> dict[str, Any]:
    """Prune stale workflow checkpoints older than retention days (default: 7)."""
    older_than_days = body.older_than_days if body else 7
    sweeper = ExpirySweeperService(db, settings=settings)
    stats = sweeper.prune_checkpoints(older_than_days=older_than_days)
    return {
        "pruned_metadata_count": stats["pruned_metadata"],
        "pruned_checkpoints_count": stats["pruned_checkpoints"],
        "pruned_blobs_count": stats["pruned_blobs"],
        "pruned_writes_count": stats["pruned_writes"],
        "message": f"Successfully pruned checkpoints older than {older_than_days} days",
    }
