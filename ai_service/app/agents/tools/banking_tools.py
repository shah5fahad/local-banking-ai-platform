"""Banking READ tools for the banking_ops node.

All tools here have risk=READ and are LLM-callable from banking_ops.
Sensitive/financial tools are registered separately for workflow nodes only.
user_id is NEVER passed as an LLM argument - it comes from GraphState.
"""
from __future__ import annotations

from app.agents.tools.registry import ToolSpec


def _list_accounts(args: dict, client, state) -> dict:
    accounts = client.list_accounts()
    # Mask: return only safe fields
    return {
        "accounts": [
            {
                "id": a["id"],
                "bank_name": a.get("bank_name"),
                "account_type": a.get("account_type"),
                "account_number_masked": a.get("account_number_masked"),
                "last4": a.get("account_number_last4") or a.get("last4"),
                "verification_status": a.get("verification_status"),
                "status": a.get("status"),
            }
            for a in accounts
        ]
    }


def _get_balance(args: dict, client, state) -> dict:
    account_id = args["account_id"]
    return client.get_balance(account_id)


def _list_transactions(args: dict, client, state) -> dict:
    filters = {
        k: args.get(k)
        for k in ["from_date", "to_date", "type", "status", "page", "page_size"]
        if args.get(k) is not None
    }
    return client.list_transactions(**filters)


def _list_beneficiaries(args: dict, client, state) -> dict:
    q = args.get("q")
    benes = client.list_beneficiaries(q=q)
    return {
        "beneficiaries": [
            {
                "id": b["id"],
                "name": b.get("name"),
                "nickname": b.get("nickname"),
                "bank_name": b.get("bank_name"),
                "last4": b.get("last4"),
                "verification_status": b.get("verification_status"),
                "approval_status": b.get("approval_status"),
            }
            for b in benes
        ]
    }


def _list_loan_offers(args: dict, client, state) -> dict:
    return {"offers": client.list_loan_offers()}


def _check_loan_eligibility(args: dict, client, state) -> dict:
    return client.check_loan_eligibility(
        {
            "loan_type": args["loan_type"],
            "amount_minor": args["amount_minor"],
            "tenure_months": args["tenure_months"],
            "monthly_income_minor": args["monthly_income_minor"],
        }
    )


def _list_cards(args: dict, client, state) -> dict:
    cards = client.list_cards()
    return {
        "cards": [
            {
                "id": c["id"],
                "last4": c.get("last4"),
                "network": c.get("network"),
                "credit_limit_minor": c.get("credit_limit_minor"),
                "outstanding_minor": c.get("outstanding_minor"),
                "status": c.get("status"),
            }
            for c in cards
        ]
    }


def _get_card_outstanding(args: dict, client, state) -> dict:
    return client.get_card_outstanding(args["card_id"])


def _get_current_bill(args: dict, client, state) -> dict:
    return client.get_current_bill(args["card_id"])


def _get_transfer_limits(args: dict, client, state) -> dict:
    return client.get_transfer_limits()


def _get_user_summary(args: dict, client, state) -> dict:
    return client.get_user_summary()


BANKING_READ_TOOLS: list[ToolSpec] = [
    ToolSpec(
        name="list_accounts",
        description=(
            "List all of the user's linked bank accounts. Returns, for each account: id, bank_name, "
            "account_type, masked account number, last4, verification_status and status. "
            "Use this when the user asks 'what accounts do I have' or refers to an account by bank name "
            "or last 4 digits. ALWAYS call this first to obtain an account `id` before calling get_balance. "
            "Does NOT return balances (use get_balance) or transactions (use list_transactions). "
            "Takes no arguments."
        ),
        args_schema={"type": "object", "properties": {}, "required": []},
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=_list_accounts,
    ),
    ToolSpec(
        name="get_balance",
        description=(
            "Get the current available balance of ONE bank account. "
            "Use when the user asks 'what is my balance' or 'how much money do I have in <bank/account>'. "
            "Requires an `account_id` taken from list_accounts; never guess or invent an ID. "
            "If the user has multiple accounts and hasn't specified which, call list_accounts first and "
            "either ask which one they mean or fetch each balance. "
            "Not for credit card dues (use get_card_outstanding) and not for a full financial overview "
            "(use get_user_summary)."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "account_id": {
                    "type": "string",
                    "description": "Internal account ID exactly as returned in the `id` field of list_accounts "
                    "(not the account number or last4).",
                }
            },
            "required": ["account_id"],
        },
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=_get_balance,
    ),
    ToolSpec(
        name="list_transactions",
        description=(
            "List the user's past transactions (transfers, card payments, credits, debits), newest first, "
            "with optional filters and pagination. "
            "Use for 'show my recent transactions', 'what did I spend last week', 'did my payment to X go through', "
            "or 'any failed transfers'. All arguments are optional; with none, it returns the latest page. "
            "Convert relative dates ('last month', 'yesterday') into absolute ISO 8601 dates before calling. "
            "Results are paginated: if the user wants more, increase `page` rather than repeating page 1. "
            "Does NOT initiate or modify any transaction, and does NOT list saved payees (use list_beneficiaries)."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "from_date": {
                    "type": "string",
                    "description": "Inclusive start date in ISO 8601 format, e.g. '2025-01-01' or "
                    "'2025-01-01T00:00:00Z'.",
                },
                "to_date": {
                    "type": "string",
                    "description": "Inclusive end date in ISO 8601 format. Must not be earlier than from_date.",
                },
                "type": {
                    "type": "string",
                    "enum": ["TRANSFER", "CARD_PAYMENT", "CREDIT", "DEBIT"],
                    "description": "Filter by transaction type. CREDIT = money received, DEBIT = money spent/withdrawn. "
                    "Omit to include all types.",
                },
                "status": {
                    "type": "string",
                    "description": "Filter by transaction status, e.g. 'SUCCESS', 'FAILED', 'PENDING'. "
                    "Omit to include all statuses.",
                },
                "page": {
                    "type": "integer",
                    "default": 1,
                    "minimum": 1,
                    "description": "1-based page number.",
                },
                "page_size": {
                    "type": "integer",
                    "default": 10,
                    "minimum": 1,
                    "description": "Number of transactions per page.",
                },
            },
            "required": [],
        },
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=_list_transactions,
    ),
    ToolSpec(
        name="list_beneficiaries",
        description=(
            "List the user's saved payees (beneficiaries) with name, nickname, bank, last4, "
            "verification_status and approval_status. "
            "Use when the user asks 'who can I send money to', wants to find a specific payee "
            "('is Rahul saved?'), or when you need to confirm a payee exists and is verified/approved. "
            "Pass `q` with the person's name or nickname to narrow results; omit it to list everyone. "
            "This only READS saved payees: it cannot add, edit or delete a beneficiary, and cannot move money."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Optional search text matched against beneficiary name or nickname, "
                    "e.g. 'Rahul'. Omit to return all beneficiaries.",
                }
            },
            "required": [],
        },
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=_list_beneficiaries,
    ),
    ToolSpec(
        name="list_loan_offers",
        description=(
            "List pre-approved loan offers already available to the user (no application needed). "
            "Use when the user asks 'do I have any loan offers', 'what loans can I get', or wants to explore "
            "options without specifying an amount. "
            "To test eligibility for a specific loan amount, tenure and income, use check_loan_eligibility instead. "
            "Takes no arguments."
        ),
        args_schema={"type": "object", "properties": {}, "required": []},
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=_list_loan_offers,
    ),
    ToolSpec(
        name="check_loan_eligibility",
        description=(
            "Check whether the user is eligible for a specific loan (type, amount, tenure) given their monthly income. "
            "Use when the user asks 'can I get a 5 lakh personal loan for 3 years?'. "
            "ALL four arguments are required; if the user hasn't provided the loan type, amount, tenure or monthly "
            "income, ask for the missing values first instead of guessing. "
            "IMPORTANT: amounts are in paise (minor units), not rupees: multiply rupees by 100 "
            "(Rs 5,00,000 -> 50000000). "
            "This is only an eligibility check; it does NOT apply for or sanction a loan."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "loan_type": {
                    "type": "string",
                    "enum": ["PERSONAL", "HOME", "AUTO"],
                    "description": "Type of loan being checked.",
                },
                "amount_minor": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Requested loan amount in paise (rupees x 100). Rs 2,00,000 = 20000000.",
                },
                "tenure_months": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Repayment tenure in months (not years). 3 years = 36.",
                },
                "monthly_income_minor": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "User's gross monthly income in paise (rupees x 100). Rs 80,000 = 8000000.",
                },
            },
            "required": ["loan_type", "amount_minor", "tenure_months", "monthly_income_minor"],
        },
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=_check_loan_eligibility,
    ),
    ToolSpec(
        name="list_cards",
        description=(
            "List the user's credit cards (masked) with id, last4, network, credit_limit_minor, "
            "outstanding_minor and status. Amounts are in paise. "
            "Use when the user asks 'what cards do I have', 'what is my credit limit', or refers to a card by "
            "its last 4 digits or network. ALWAYS call this first to obtain a card `id` before calling "
            "get_card_outstanding or get_current_bill. "
            "Takes no arguments. Full card numbers, CVV and PIN are never available."
        ),
        args_schema={"type": "object", "properties": {}, "required": []},
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=_list_cards,
    ),
    ToolSpec(
        name="get_card_outstanding",
        description=(
            "Get the total outstanding (amount currently owed) on ONE credit card. "
            "Use for 'how much do I owe on my card' or 'what's my card dues'. "
            "Requires a `card_id` from list_cards; never guess it. "
            "For the itemised statement with due date and minimum amount due, use get_current_bill instead."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "string",
                    "description": "Card ID exactly as returned in the `id` field of list_cards (not the last4).",
                }
            },
            "required": ["card_id"],
        },
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=_get_card_outstanding,
    ),
    ToolSpec(
        name="get_current_bill",
        description=(
            "Get the current billing statement of ONE credit card (statement amount, due date, minimum due, "
            "and related bill details). "
            "Use for 'when is my card bill due', 'what is my minimum due' or 'show my latest statement'. "
            "Requires a `card_id` from list_cards; never guess it. "
            "For only the total amount owed, get_card_outstanding is sufficient. "
            "This only reads the bill; it does NOT make a payment."
        ),
        args_schema={
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "string",
                    "description": "Card ID exactly as returned in the `id` field of list_cards (not the last4).",
                }
            },
            "required": ["card_id"],
        },
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=_get_current_bill,
    ),
    ToolSpec(
        name="get_transfer_limits",
        description=(
            "Get the user's money-transfer limits (per-transaction and daily) and how much of the daily limit "
            "has already been used today. "
            "Use for 'what is my transfer limit', 'how much can I still send today', or to check whether a "
            "planned transfer amount would fit within limits. "
            "Takes no arguments. Does not perform a transfer."
        ),
        args_schema={"type": "object", "properties": {}, "required": []},
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=_get_transfer_limits,
    ),
    ToolSpec(
        name="get_user_summary",
        description=(
            "Get a high-level overview of the user's banking profile (accounts, cards and key figures in one call). "
            "Use for broad questions like 'give me an overview of my finances' or 'what's my account status'. "
            "For a specific balance, card due or transaction history, prefer the dedicated tool "
            "(get_balance, get_card_outstanding, list_transactions) since it returns more precise data. "
            "Takes no arguments."
        ),
        args_schema={"type": "object", "properties": {}, "required": []},
        risk="READ",
        allowed_nodes={"banking_ops"},
        handler=_get_user_summary,
    ),
]