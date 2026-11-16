# Local Banking AI Platform

A local, demonstration-grade banking platform with an AI conversational assistant.
It is **not** a production banking system and makes **no regulatory-compliance claims**.

## Components

| Component | Tech | Owns |
|---|---|---|
| Banking API Service | FastAPI, SQLAlchemy, Alembic, SQLite | Users, accounts, beneficiaries, transfers, loans, cards, audit |
| AI Chat Service | FastAPI, LangChain, LangGraph, ChromaDB | Conversations, agents, RAG, HITL workflow state |
| Frontend | Streamlit | UI only, no business logic |

Hard rule: the AI service never touches the banking database. It calls authenticated banking REST APIs only.

## Quick start (target state, after implementation)

```bash
cp .env.example .env          # fill in secrets and LLM/embedding provider
docker compose up --build
# Banking API   http://localhost:8001/docs
# AI Chat API   http://localhost:8002/docs
# Streamlit UI  http://localhost:8501
```

## Documentation index

| File | Purpose |
|---|---|
| [docs/requirements.md](docs/requirements.md) | Functional/technical requirements, assumptions |
| [docs/scope.md](docs/scope.md) | In/out of scope, NFRs |
| [docs/architecture.md](docs/architecture.md) | System architecture and component diagram |
| [docs/low_level_design.md](docs/low_level_design.md) | Folder structure, modules, classes |
| [docs/database_design.md](docs/database_design.md) | ERDs and schemas |
| [docs/api_specification.md](docs/api_specification.md) | API contracts |
| [docs/agent_architecture.md](docs/agent_architecture.md) | LangGraph agents, state, routing |
| [docs/rag_design.md](docs/rag_design.md) | Ingestion and retrieval |
| [docs/hitl_workflows.md](docs/hitl_workflows.md) | Approval and authentication flows |
| [docs/security.md](docs/security.md) | Security controls and threat model |
| [docs/testing.md](docs/testing.md) | Test strategy |
| [TODO.md](TODO.md) | Phased task breakdown |
| [CHANGELOG.md](CHANGELOG.md), [CONTRIBUTING.md](CONTRIBUTING.md) | Process |

## Status
Phase 0: architecture and planning complete. Implementation starts only after this design is reviewed (see open questions in `docs/requirements.md`).

NVIDIA_API_KEY=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
