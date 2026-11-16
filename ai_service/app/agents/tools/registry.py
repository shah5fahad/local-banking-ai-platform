"""Tool registry with risk levels and allowed_nodes enforcement.

Tools are registered with:
- name: unique identifier
- description: for LLM tool calling  
- risk: READ | WRITE_LOW | SENSITIVE | FINANCIAL
- allowed_nodes: set of node names that can invoke this tool
- handler: callable(args: dict, client: BankingClient, state: GraphState) -> dict

Security: handler is called only if the calling node is in allowed_nodes.
user_id is NEVER an LLM-supplied argument; it comes from GraphState.user_id.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

Risk = Literal["READ", "WRITE_LOW", "SENSITIVE", "FINANCIAL"]


@dataclass
class ToolSpec:
    name: str
    description: str
    args_schema: dict  # JSON Schema for LLM tool calling
    risk: Risk
    allowed_nodes: set[str]
    handler: Callable[[dict, Any, Any], dict]  # (args, client, state) -> result
    requires_approval: bool = False


class ToolRegistry:
    """Central registry of all banking tools."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def get_for_node(self, node_name: str) -> list[ToolSpec]:
        """Return tools whose allowed_nodes includes node_name."""
        return [t for t in self._tools.values() if node_name in t.allowed_nodes]

    def get_llm_tools_for_node(self, node_name: str) -> list[dict]:
        """Return OpenAI-format tool schemas for tools allowed in this node."""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.args_schema,
                },
            }
            for t in self.get_for_node(node_name)
        ]

    def invoke(self, name: str, args: dict, calling_node: str, client: Any, state: Any) -> dict:
        """Invoke a tool, enforcing allowed_nodes."""
        spec = self.get(name)
        if spec is None:
            return {"error": f"Unknown tool: {name}", "success": False}
        if calling_node not in spec.allowed_nodes:
            return {"error": f"Tool {name} not allowed in node {calling_node}", "success": False}
        try:
            result = spec.handler(args, client, state)
            return {"result": result, "success": True}
        except Exception as exc:
            return {"error": str(exc), "success": False, "error_code": type(exc).__name__}


# ---------------------------------------------------------------------------
# Global registry instance
# ---------------------------------------------------------------------------
_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
        _register_all(_registry)
    return _registry


def reset_registry() -> None:
    """Reset registry singleton (primarily for testing)."""
    global _registry
    _registry = None


def _register_all(registry: ToolRegistry) -> None:
    """Register all tools in the registry."""
    from app.agents.tools.banking_tools import BANKING_READ_TOOLS
    for spec in BANKING_READ_TOOLS:
        registry.register(spec)
