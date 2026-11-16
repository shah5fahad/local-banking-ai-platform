"""Unit tests for ToolRegistry and banking read tools."""
from __future__ import annotations

import pytest
from app.agents.tools.registry import ToolRegistry, ToolSpec, get_registry, reset_registry


def test_tool_registered_and_retrieved():
    registry = ToolRegistry()
    dummy_spec = ToolSpec(
        name="test_tool",
        description="A test tool",
        args_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        risk="READ",
        allowed_nodes={"test_node"},
        handler=lambda args, client, state: {"val": args["x"] * 2},
    )
    registry.register(dummy_spec)

    retrieved = registry.get("test_tool")
    assert retrieved is not None
    assert retrieved.name == "test_tool"
    assert retrieved.risk == "READ"

    tools_for_node = registry.get_for_node("test_node")
    assert len(tools_for_node) == 1
    assert tools_for_node[0].name == "test_tool"

    llm_schemas = registry.get_llm_tools_for_node("test_node")
    assert len(llm_schemas) == 1
    assert llm_schemas[0]["type"] == "function"
    assert llm_schemas[0]["function"]["name"] == "test_tool"


def test_tool_not_allowed_in_wrong_node():
    registry = ToolRegistry()
    dummy_spec = ToolSpec(
        name="secure_action",
        description="A sensitive action",
        args_schema={"type": "object", "properties": {}},
        risk="FINANCIAL",
        allowed_nodes={"workflow_node"},
        handler=lambda args, client, state: {"status": "executed"},
    )
    registry.register(dummy_spec)

    # Calling from an unauthorized node should be blocked
    result = registry.invoke("secure_action", {}, "banking_ops", None, {})
    assert result["success"] is False
    assert "not allowed in node banking_ops" in result["error"]

    # Calling from allowed node should succeed
    allowed_result = registry.invoke("secure_action", {}, "workflow_node", None, {})
    assert allowed_result["success"] is True
    assert allowed_result["result"] == {"status": "executed"}


def test_invoke_returns_error_on_unknown_tool():
    registry = ToolRegistry()
    result = registry.invoke("non_existent_tool", {}, "banking_ops", None, {})
    assert result["success"] is False
    assert "Unknown tool: non_existent_tool" in result["error"]


def test_tool_handler_exception_handled():
    def failing_handler(args, client, state):
        raise ValueError("Invalid parameters provided")

    registry = ToolRegistry()
    spec = ToolSpec(
        name="failing_tool",
        description="Fails intentionally",
        args_schema={},
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=failing_handler,
    )
    registry.register(spec)

    result = registry.invoke("failing_tool", {}, "banking_ops", None, {})
    assert result["success"] is False
    assert "Invalid parameters provided" in result["error"]
    assert result["error_code"] == "ValueError"


def test_global_registry_contains_banking_read_tools():
    reset_registry()
    registry = get_registry()

    expected_tools = [
        "list_accounts",
        "get_balance",
        "list_transactions",
        "list_beneficiaries",
        "list_loan_offers",
        "check_loan_eligibility",
        "list_cards",
        "get_card_outstanding",
        "get_current_bill",
        "get_transfer_limits",
        "get_user_summary",
    ]

    for tool_name in expected_tools:
        spec = registry.get(tool_name)
        assert spec is not None, f"Tool {tool_name} should be registered in global registry"
        assert spec.risk == "READ"
        assert "banking_ops" in spec.allowed_nodes

    banking_ops_tools = registry.get_for_node("banking_ops")
    registered_names = [t.name for t in banking_ops_tools]
    for tool_name in expected_tools:
        assert tool_name in registered_names
