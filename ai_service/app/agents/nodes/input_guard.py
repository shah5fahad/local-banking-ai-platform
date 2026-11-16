"""Input guard LangGraph node."""
from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from app.agents.state import GraphState
from app.agents.guards.input_guard import validate_message


def input_guard_node(state: GraphState, config: RunnableConfig = None) -> dict:
    """Validate and sanitise user message."""
    raw = state.get("user_message", "")
    sanitised, blocked, reason = validate_message(raw)

    update: dict = {
        "input_blocked": blocked,
        "input_block_reason": reason,
    }

    if blocked:
        update["response"] = reason or "I cannot process this message."
    else:
        update["user_message"] = sanitised
        update["messages"] = [HumanMessage(content=sanitised)]
        update["response"] = None
        update["citations"] = None

    return update
