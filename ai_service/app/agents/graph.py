"""LangGraph graph assembly with SQLite checkpointer.

The graph is built once at startup and reused across requests.
The checkpointer persists workflow state between interrupt/resume cycles.

Token context:
  The user's access token is NEVER in GraphState.
  It is passed at invoke/resume time via:
    config = {"configurable": {"thread_id": conversation_id, "access_token": token}}
  Nodes retrieve it via:
    token = config["configurable"].get("access_token", "")
"""
from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

try:
    from langgraph.checkpoint.sqlite import SqliteSaver
except ImportError:
    try:
        from langgraph_checkpoint_sqlite import SqliteSaver  # type: ignore
    except ImportError:
        from langgraph.checkpoint.memory import MemorySaver as SqliteSaver  # type: ignore

from app.agents.state import GraphState


def _route_after_input_guard(state: GraphState) -> str:
    """Route: if input was blocked, go to response; else go to supervisor."""
    return "response" if state.get("input_blocked") else "supervisor"


def _route_after_supervisor(state: GraphState) -> str:
    """Route based on agent_route set by the supervisor node."""
    route = state.get("agent_route", "unsupported")
    route_map: dict[str, str] = {
        "banking_ops": "banking_ops",
        "workflow_beneficiary": "workflow_beneficiary",
        "workflow_transfer": "workflow_transfer",
        "workflow_loan": "workflow_loan",
        "workflow_card_payment": "workflow_card_payment",
        "policy_rag": "policy_rag",
        "external_research": "external_research",
        "reject_out_of_domain": "response",
        "unsupported": "response",
    }
    return route_map.get(str(route), "response")


def _route_after_workflow(state: GraphState) -> str:
    """Route to approval gate if workflow prepared a pending action, else to response."""
    if state.get("pending_action"):
        return "approval_gate"
    return "response"


def _route_after_approval_gate(state: GraphState) -> str:
    """Route after approval gate: execute if confirmed and auth complete, else to response."""
    status = state.get("approval_status")
    auth_status = state.get("authentication_status")
    if status == "CONFIRMED" and auth_status in ("COMPLETED", "NONE"):
        return "execute"
    return "response"


def build_graph(checkpointer: Any | None = None) -> Any:  # noqa: ANN401
    """Assemble and compile the main LangGraph.

    Import nodes lazily to avoid circular imports.
    """
    from app.agents.nodes.approval_gate import approval_gate_node
    from app.agents.nodes.banking_ops import banking_ops_node
    from app.agents.nodes.execute import execute_node
    from app.agents.nodes.external_research import external_research_node
    from app.agents.nodes.input_guard import input_guard_node
    from app.agents.nodes.policy_rag import policy_rag_node
    from app.agents.nodes.response import response_node
    from app.agents.nodes.supervisor import supervisor_node
    from app.agents.workflows.beneficiary import workflow_beneficiary_node
    from app.agents.workflows.card_payment import workflow_card_payment_node
    from app.agents.workflows.loan import workflow_loan_node
    from app.agents.workflows.transfer import workflow_transfer_node

    builder = StateGraph(GraphState)

    # Register nodes
    builder.add_node("input_guard", input_guard_node)
    builder.add_node("supervisor", supervisor_node)
    builder.add_node("banking_ops", banking_ops_node)
    builder.add_node("policy_rag", policy_rag_node)
    builder.add_node("external_research", external_research_node)
    builder.add_node("workflow_beneficiary", workflow_beneficiary_node)
    builder.add_node("workflow_transfer", workflow_transfer_node)
    builder.add_node("workflow_loan", workflow_loan_node)
    builder.add_node("workflow_card_payment", workflow_card_payment_node)
    builder.add_node("approval_gate", approval_gate_node)
    builder.add_node("execute", execute_node)
    builder.add_node("response", response_node)

    # Entry
    builder.set_entry_point("input_guard")

    # Edges
    builder.add_conditional_edges(
        "input_guard",
        _route_after_input_guard,
        {"response": "response", "supervisor": "supervisor"},
    )
    builder.add_conditional_edges(
        "supervisor",
        _route_after_supervisor,
        {
            "banking_ops": "banking_ops",
            "workflow_beneficiary": "workflow_beneficiary",
            "workflow_transfer": "workflow_transfer",
            "workflow_loan": "workflow_loan",
            "workflow_card_payment": "workflow_card_payment",
            "policy_rag": "policy_rag",
            "external_research": "external_research",
            "response": "response",
        },
    )
    for node in [
        "banking_ops",
        "policy_rag",
        "external_research",
    ]:
        builder.add_edge(node, "response")

    for node in [
        "workflow_beneficiary",
        "workflow_transfer",
        "workflow_loan",
        "workflow_card_payment",
    ]:
        builder.add_conditional_edges(
            node,
            _route_after_workflow,
            {"approval_gate": "approval_gate", "response": "response"},
        )

    builder.add_conditional_edges(
        "approval_gate",
        _route_after_approval_gate,
        {"execute": "execute", "response": "response"},
    )
    builder.add_edge("execute", "response")
    builder.add_edge("response", END)

    if checkpointer is not None:
        return builder.compile(checkpointer=checkpointer)
    return builder.compile()


# Module-level singleton
_graph: Any = None
_checkpointer: Any = None


def get_graph(db_path: str = "./ai_service.db") -> Any:  # noqa: ANN401
    """Return the compiled graph singleton, initializing if needed."""
    global _graph, _checkpointer
    if _graph is None:
        import sqlite3
        conn = sqlite3.connect(db_path, check_same_thread=False)
        try:
            _checkpointer = SqliteSaver(conn)
        except Exception:
            if hasattr(SqliteSaver, "from_conn_string"):
                _checkpointer = SqliteSaver.from_conn_string(db_path)
            else:
                _checkpointer = SqliteSaver()
        _graph = build_graph(_checkpointer)
    return _graph


def reset_graph() -> None:
    """Reset the compiled graph and checkpointer singleton (primarily for testing)."""
    global _graph, _checkpointer
    _graph = None
    _checkpointer = None


def invoke_graph(state_input: dict, config: dict) -> dict:
    """Invoke the graph with a state input and config.

    config must include:
        {"configurable": {"thread_id": conversation_id, "access_token": bearer_token}}

    The access_token is used by nodes to call the banking API but is
    NEVER stored in GraphState or the checkpoint database.
    """
    graph = get_graph()
    return graph.invoke(state_input, config=config)


def resume_graph(
    thread_id: str,
    resume_payload: Any,  # noqa: ANN401
    access_token: str | None = None,
) -> dict[str, Any]:
    """Resume an interrupted graph execution using LangGraph Command(resume=...).

    Args:
        thread_id: conversation / thread ID for the checkpoint.
        resume_payload: Command or payload passed to resume.
        access_token: raw Bearer token injected into config['configurable'].

    Returns:
        The resulting GraphState dict after execution.
    """
    from langgraph.types import Command

    graph = get_graph()
    config = {
        "configurable": {
            "thread_id": thread_id,
            "access_token": access_token or "",
        }
    }
    if isinstance(resume_payload, Command):
        cmd = resume_payload
    else:
        update_dict: dict[str, Any] = {}
        if isinstance(resume_payload, dict):
            if resume_payload.get("approval_id"):
                update_dict["approval_id"] = resume_payload["approval_id"]
            if resume_payload.get("authorization_id"):
                update_dict["authorization_id"] = resume_payload["authorization_id"]
        cmd = Command(resume=resume_payload, update=update_dict if update_dict else None)
    return graph.invoke(cmd, config=config)
