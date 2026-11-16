"""Banking ops node: handles READ queries using registered tools."""
from __future__ import annotations

import json
import logging
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import GraphState, ToolResultRef
from app.agents.tools.registry import get_registry
from app.core.config import get_settings
from app.integrations.banking_client import BankingClient
from app.integrations.llm_factory import (
    create_llm,
    extract_message_text,
    sanitize_messages_for_llm,
)

logger = logging.getLogger(__name__)


def banking_ops_node(state: GraphState, config: RunnableConfig = None) -> dict:
    """Handle banking READ queries by calling registered tools."""
    settings = get_settings()
    access_token = (config or {}).get("configurable", {}).get("access_token", "")

    client = BankingClient(settings=settings, access_token=access_token)
    registry = get_registry()

    # Build tool schemas for LLM
    tool_schemas = registry.get_llm_tools_for_node("banking_ops")
    llm = create_llm(settings)

    input_messages = sanitize_messages_for_llm(
        state.get("messages", []),
        user_message=state.get("user_message", ""),
    )

    # For fake LLM or when tools can't be bound, use simple invocation
    try:
        llm_with_tools = llm.bind_tools(
            [{"type": "function", "function": s["function"]} for s in tool_schemas]
        )
        response = llm_with_tools.invoke(input_messages)
    except Exception as exc:
        logger.warning("Tool-bound LLM invocation failed in banking_ops: %s", exc)
        try:
            response = llm.invoke(input_messages)
        except Exception as inner_exc:
            logger.warning("Fallback LLM invocation failed in banking_ops: %s", inner_exc)
            response = AIMessage(content="I am having trouble processing your request at the moment.")

    if not isinstance(response, AIMessage):
        content = extract_message_text(response.content if hasattr(response, "content") else response)
        response = AIMessage(content=content)

    tool_results: list[ToolResultRef] = []

    # Process tool calls if any
    if hasattr(response, "tool_calls") and response.tool_calls:
        for tc in response.tool_calls:
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            result = registry.invoke(tool_name, tool_args, "banking_ops", client, state)
            tool_results.append(
                ToolResultRef(
                    tool_name=tool_name,
                    result_masked=json.dumps(result.get("result", result)),
                    success=result.get("success", False),
                    error_code=result.get("error_code"),
                )
            )
    elif access_token:
        # Fallback for fake LLM or when tools were not called by LLM
        intent = state.get("intent")
        query = (state.get("user_message") or "").lower()
        fallback_tool: str | None = None
        fallback_args: dict = {}

        if intent == "BANK_READ":
            if "transaction" in query:
                fallback_tool = "list_transactions"
            elif "card" in query:
                fallback_tool = "list_cards"
            else:
                fallback_tool = "list_accounts"
        elif intent == "LOAN_INFO":
            fallback_tool = "list_loan_offers"
        elif intent == "CARD_INFO":
            fallback_tool = "list_cards"

        if fallback_tool:
            result = registry.invoke(fallback_tool, fallback_args, "banking_ops", client, state)
            tool_results.append(
                ToolResultRef(
                    tool_name=fallback_tool,
                    result_masked=json.dumps(result.get("result", result)),
                    success=result.get("success", False),
                    error_code=result.get("error_code"),
                )
            )

    return {
        "tool_results": tool_results,
        "messages": [response],
    }
