"""Response node: compose final response and run output guard."""
from __future__ import annotations

import logging
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

from app.agents.guards.output_guard import run_output_guard
from app.agents.state import GraphState
from app.core.config import get_settings
from app.integrations.llm_factory import (
    create_llm,
    extract_message_text,
    sanitize_messages_for_llm,
)

logger = logging.getLogger(__name__)

UNSUPPORTED_RESPONSE = "I'm sorry, this feature isn't available yet. For assistance, please contact customer support."
OUT_OF_DOMAIN_RESPONSE = "I can only help with banking and financial questions. For other topics, please use a general assistant."
INPUT_BLOCKED_PREFIX = "⚠️ "


def response_node(state: GraphState, config: RunnableConfig = None) -> dict:
    """Compose and sanitise the final response."""
    citations = state.get("citations")

    # If response is already set (by other nodes or block), just sanitise it
    if state.get("response"):
        response = state["response"]
        if state.get("input_blocked") and not str(response).startswith(INPUT_BLOCKED_PREFIX):
            response = INPUT_BLOCKED_PREFIX + response
        final = run_output_guard(response)
        return {
            "response": final,
            "messages": [AIMessage(content=final)],
            "citations": citations,
        }

    # Determine canned response for terminal routes
    route = state.get("agent_route", "unsupported")
    if route == "reject_out_of_domain":
        final = run_output_guard(OUT_OF_DOMAIN_RESPONSE)
        return {"response": final, "messages": [AIMessage(content=final)], "citations": citations}
    if route == "unsupported":
        final = run_output_guard(UNSUPPORTED_RESPONSE)
        return {"response": final, "messages": [AIMessage(content=final)], "citations": citations}

    # Compose from tool results if any
    settings = get_settings()
    llm = create_llm(settings)
    tool_results = state.get("tool_results", [])

    clean_messages = sanitize_messages_for_llm(
        state.get("messages", []),
        user_message=state.get("user_message", ""),
    )

    if tool_results:
        tool_summary = "\n".join(
            f"- {r.get('tool_name')}: {r.get('result_masked')}" for r in tool_results
        )
        system = f"""Based on the following tool results, compose a helpful banking assistant response.
Present the information clearly. Do not add or invent any information not present in the results.
Tool results:\n{tool_summary}"""
        response = llm.invoke(
            [
                SystemMessage(content=system),
                *clean_messages,
            ]
        )
        response_text = extract_message_text(response.content if hasattr(response, "content") else response)
    else:
        prompt_messages = clean_messages or [HumanMessage(content=state.get("user_message", "") or "Hello")]
        response = llm.invoke(prompt_messages)
        response_text = extract_message_text(response.content if hasattr(response, "content") else response)

    final = run_output_guard(response_text)
    return {
        "response": final,
        "messages": [AIMessage(content=final)],
        "citations": citations,
    }
