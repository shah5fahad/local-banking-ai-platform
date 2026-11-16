"""Supervisor node: intent classification and routing.

Uses structured LLM output to classify intent and select route.
Applies deterministic overlay rules after LLM classification.
The supervisor has NO tools - it only classifies.
"""
from __future__ import annotations

import json
import logging
import re
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel, Field

from app.agents.state import GraphState, Intent, Route
from app.core.config import get_settings
from app.integrations.llm_factory import create_llm, extract_message_text

logger = logging.getLogger(__name__)

SUPERVISOR_SYSTEM_PROMPT = """
You are a banking assistant intent classifier. Your ONLY job is to classify the user's message
into one of the defined intents and select the appropriate route.

You have NO ability to execute actions, call tools, or access any data.
You MUST respond with valid JSON only.

Intent definitions:
- BANK_READ: User wants to view their own banking data (balances, transactions, accounts, cards, loans)
- BENEFICIARY_ADD: User wants to add a new beneficiary
- TRANSFER: User wants to transfer money
- LOAN_INFO: User wants information about loans (not applying)
- LOAN_APPLY: User wants to apply for a loan
- CARD_INFO: User wants to view credit card information
- CARD_PAYMENT: User wants to pay their credit card bill
- POLICY_QA: User is asking about bank policies, terms, fees, or procedures
- EXTERNAL_INFO: User wants general financial/economic information (not specific to their account)
- SMALL_TALK_BANKING: Greeting or casual banking-related chat
- UNSUPPORTED_BANKING: Banking action we don't support yet
- OUT_OF_DOMAIN: Completely unrelated to banking or finance

Route selection:
- BANK_READ → banking_ops
- BENEFICIARY_ADD → workflow_beneficiary
- TRANSFER → workflow_transfer
- LOAN_INFO → banking_ops
- LOAN_APPLY → workflow_loan
- CARD_INFO → banking_ops
- CARD_PAYMENT → workflow_card_payment
- POLICY_QA → policy_rag
- EXTERNAL_INFO → external_research
- SMALL_TALK_BANKING → banking_ops
- UNSUPPORTED_BANKING → unsupported
- OUT_OF_DOMAIN → reject_out_of_domain

Respond with JSON: {"intent": "...", "route": "...", "confidence": 0.0-1.0,
                   "needs_api": bool, "needs_docs": bool, "needs_web": bool}
"""

# Deterministic routing overrides
ROUTE_OVERRIDES: dict[str, Route] = {
    "BANK_READ": "banking_ops",
    "BENEFICIARY_ADD": "workflow_beneficiary",
    "TRANSFER": "workflow_transfer",
    "LOAN_INFO": "banking_ops",
    "LOAN_APPLY": "workflow_loan",
    "CARD_INFO": "banking_ops",
    "CARD_PAYMENT": "workflow_card_payment",
    "POLICY_QA": "policy_rag",
    "EXTERNAL_INFO": "external_research",
    "SMALL_TALK_BANKING": "banking_ops",
    "UNSUPPORTED_BANKING": "unsupported",
    "OUT_OF_DOMAIN": "reject_out_of_domain",
}

LOW_CONFIDENCE_THRESHOLD = 0.5


class SupervisorOutput(BaseModel):
    intent: str = Field(default="UNSUPPORTED_BANKING")
    route: str = Field(default="unsupported")
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    needs_api: bool = Field(default=False)
    needs_docs: bool = Field(default=False)
    needs_web: bool = Field(default=False)


def classify_heuristically(message: str) -> SupervisorOutput | None:
    """Heuristic intent classifier for routing table specs and fake LLM mode."""
    text = message.lower().strip()
    if not text:
        return None

    # 1. OUT_OF_DOMAIN
    if any(k in text for k in ["python", "decorator", "recipe", "weather", "cake", "code", "quantum", "joke", "movie", "song", "football", "cricket"]):
        return SupervisorOutput(intent="OUT_OF_DOMAIN", route="reject_out_of_domain", confidence=0.98)

    # 2. POLICY_QA (bank policy, terms, rules)
    if any(k in text for k in ["policy", "bank policy", "loan policy", "terms and conditions", "terms & conditions", "interest rate policy", "guidelines"]):
        return SupervisorOutput(intent="POLICY_QA", route="policy_rag", confidence=0.95, needs_docs=True)

    # 3. BENEFICIARY_ADD
    if "beneficiary" in text and any(k in text for k in ["add", "new", "create", "register"]):
        return SupervisorOutput(intent="BENEFICIARY_ADD", route="workflow_beneficiary", confidence=0.95, needs_api=True)

    # 4. TRANSFER
    if any(k in text for k in ["transfer", "send money", "send ₹", "send rs"]) or (
        "transfer" in text and any(c in text for c in ["₹", "rs", "to "])
    ):
        return SupervisorOutput(intent="TRANSFER", route="workflow_transfer", confidence=0.95, needs_api=True)

    # 5. CARD_PAYMENT
    if any(k in text for k in ["pay my credit card", "pay card", "pay credit card bill", "card bill payment", "pay card bill"]) or (
        "pay" in text and "card" in text
    ):
        return SupervisorOutput(intent="CARD_PAYMENT", route="workflow_card_payment", confidence=0.95, needs_api=True)

    # 6. CARD_INFO
    if ("card" in text or "credit card" in text) and any(
        k in text for k in ["due", "outstanding", "bill", "limit", "details", "info", "statement"]
    ):
        return SupervisorOutput(intent="CARD_INFO", route="banking_ops", confidence=0.95, needs_api=True)

    # 7. LOAN_APPLY
    if "loan" in text and any(k in text for k in ["apply", "application", "need a loan", "want a loan"]):
        return SupervisorOutput(intent="LOAN_APPLY", route="workflow_loan", confidence=0.95, needs_api=True)

    # 8. LOAN_INFO
    if "loan" in text and any(k in text for k in ["offer", "pre-approved", "preapproved", "eligib", "show my"]):
        return SupervisorOutput(intent="LOAN_INFO", route="banking_ops", confidence=0.95, needs_api=True)

    # 9. EXTERNAL_INFO
    if any(k in text for k in ["repo rate", "rbi", "inflation rate", "gdp", "prime lending rate", "sensex", "nifty"]):
        return SupervisorOutput(intent="EXTERNAL_INFO", route="external_research", confidence=0.95, needs_web=True)

    # 10. BANK_READ
    if any(k in text for k in ["balance", "transaction", "statement", "account", "passbook"]):
        return SupervisorOutput(intent="BANK_READ", route="banking_ops", confidence=0.95, needs_api=True)

    # 11. SMALL_TALK_BANKING
    if any(k in text for k in ["hello", "hi", "hey", "good morning", "good evening", "how are you"]):
        return SupervisorOutput(intent="SMALL_TALK_BANKING", route="banking_ops", confidence=0.90)

    # 12. UNSUPPORTED_BANKING
    if any(k in text for k in ["chequebook", "checkbook", "locker", "demat", "forex card", "physical card"]):
        return SupervisorOutput(intent="UNSUPPORTED_BANKING", route="unsupported", confidence=0.90)

    return None


def supervisor_node(state: GraphState, config: RunnableConfig = None) -> dict:
    """Classify intent and select route. No tools, no data access."""
    settings = get_settings()
    llm = create_llm(settings, temperature=0.0)

    messages = [
        SystemMessage(content=SUPERVISOR_SYSTEM_PROMPT),
        HumanMessage(content=state.get("user_message", "")),
    ]

    try:
        response = llm.invoke(messages)
        content = extract_message_text(response.content if hasattr(response, "content") else response)

        # Parse JSON response
        # Handle markdown code blocks
        content = content.strip()
        if content.startswith("```"):
            parts = content.split("```")
            if len(parts) >= 2:
                content = parts[1]
                if content.startswith("json"):
                    content = content[4:]
            content = content.strip()

        output = SupervisorOutput(**json.loads(content))

    except Exception as exc:
        logger.warning("Supervisor LLM failed: %s", exc)
        from app.integrations.llm_factory import _test_fake_llm

        heuristic = None
        if _test_fake_llm is None:
            heuristic = classify_heuristically(state.get("user_message", ""))

        if heuristic is not None:
            output = heuristic
        else:
            output = SupervisorOutput(
                intent="UNSUPPORTED_BANKING",
                route="unsupported",
                confidence=0.0,
            )

    # Apply deterministic routing overlay
    override_route: Route = ROUTE_OVERRIDES.get(output.intent, "unsupported")  # type: ignore

    # Low confidence → ask for clarification (route to unsupported for now)
    if output.confidence < LOW_CONFIDENCE_THRESHOLD:
        logger.info(
            "Low confidence classification %.2f, defaulting to unsupported",
            output.confidence,
        )
        override_route = "unsupported"

    logger.info(
        "Supervisor: intent=%s route=%s confidence=%.2f",
        output.intent,
        override_route,
        output.confidence,
    )

    return {
        "intent": output.intent,
        "agent_route": override_route,
        "route_confidence": output.confidence,
    }
