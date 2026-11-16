"""Stub workflow nodes for Phase 3. Full implementations in Phase 5."""
from __future__ import annotations

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import GraphState
from app.agents.workflows.beneficiary import workflow_beneficiary_node
from app.agents.workflows.card_payment import workflow_card_payment_node
from app.agents.workflows.loan import workflow_loan_node
from app.agents.workflows.transfer import workflow_transfer_node

__all__ = [
    "workflow_beneficiary_node",
    "workflow_card_payment_node",
    "workflow_loan_node",
    "workflow_transfer_node",
]
