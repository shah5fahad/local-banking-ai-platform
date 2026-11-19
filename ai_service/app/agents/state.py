"""LangGraph GraphState definition.

CRITICAL security rules:
- access_token is NEVER stored in state - injected via config["configurable"] at runtime
- No PINs, passwords, OTPs, or full account numbers in state
- Only masked content in messages and tool_results
"""
from __future__ import annotations

from typing import Annotated, Literal
from typing_extensions import TypedDict
from langgraph.graph.message import add_messages
from langchain_core.messages import AnyMessage

# Intent enum values
Intent = Literal[
    "BANK_READ",
    "BENEFICIARY_ADD",
    "TRANSFER",
    "LOAN_INFO",
    "LOAN_APPLY",
    "CARD_INFO",
    "CARD_PAYMENT",
    "POLICY_QA",
    "EXTERNAL_INFO",
    "SMALL_TALK_BANKING",
    "UNSUPPORTED_BANKING",
    "OUT_OF_DOMAIN",
]

# Route enum values
Route = Literal[
    "banking_ops",
    "workflow_beneficiary",
    "workflow_transfer",
    "workflow_loan",
    "workflow_card_payment",
    "policy_rag",
    "external_research",
    "reject_out_of_domain",
    "unsupported",
]


class ToolResultRef(TypedDict, total=False):
    tool_name: str
    result_masked: str  # JSON-serialisable masked summary
    success: bool
    error_code: str | None


class PendingAction(TypedDict, total=False):
    workflow: str  # BENEFICIARY, TRANSFER, LOAN, CARD_PAYMENT
    banking_resource_id: str | None  # e.g. transfer id
    summary_masked: dict  # masked display fields
    summary_hash: str
    stage: str  # CONFIRM, AUTH_REQUIRED, AUTHENTICATED
    action_data: dict | None  # payload data for post-approval execution



def take_last_value(current: str | None, update: str | None) -> str | None:
    """Reducer that resolves concurrent writes by taking the latest update."""
    return update


class GraphState(TypedDict, total=False):
    # Identity - set from validated JWT, never from LLM
    user_id: str
    session_id: str
    conversation_id: str
    request_id: str

    # Input
    user_message: str

    # Routing
    intent: Intent | None
    agent_route: Route | None
    route_confidence: float

    # Conversation history (masked content only)
    messages: Annotated[list[AnyMessage], add_messages]

    # Tool results (masked/summarised, no raw secrets)
    tool_results: list[ToolResultRef]

    # HITL workflow state
    pending_action: PendingAction | None
    approval_status: Literal["NONE", "PENDING", "CONFIRMED", "REJECTED", "EXPIRED"]
    authentication_status: Literal["NONE", "REQUIRED", "COMPLETED", "FAILED"]
    approval_id: Annotated[str | None, take_last_value]  # PendingApproval.id from AI DB
    authorization_id: Annotated[str | None, take_last_value]  # Authorization ID from direct Banking API authentication

    # Output
    transaction_reference: str | None
    response: str | None
    citations: list[dict] | None  # [{doc_name, version, page, section}]

    # Flags
    input_blocked: bool  # True if input_guard rejected the message
    input_block_reason: str | None
    error_code: str | None
