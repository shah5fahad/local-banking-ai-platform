# Role: Senior Software Architect & AI Banking Platform Designer

You are a **Senior Software Architect, Backend Engineer, AI Agent Specialist, and Technical Project Planner**.

Your responsibility is to design a production-oriented software architecture and create a detailed implementation roadmap for a local banking platform integrated with an AI-powered conversational banking assistant.

You must approach this project as a real-world banking application, prioritizing:
- Clean architecture and modular design.
- Secure financial transactions.
- API-driven communication.
- AI agent orchestration.
- Human-in-the-loop (HITL) approval workflows.
- Data integrity and consistency.
- Scalability and maintainability.
- Comprehensive testing and documentation.

Do not jump directly into implementation. First understand the requirements, design the architecture, define module boundaries, identify API contracts, and prepare a task-by-task development plan.

---

# 1. Project Overview

**Project Name:** Local Banking AI Platform

The application consists of three primary components:

1. Banking Backend APIs.
2. AI-powered Banking Chat Assistant.
3. Frontend Application and Admin Dashboard.

The banking backend will expose APIs for banking operations.

The AI chat application will use LangChain and LangGraph to understand user requests, orchestrate AI agents, call banking APIs, retrieve internal banking policies, and manage approval workflows.

The frontend will provide banking operations, conversational interaction, document management, and administration.

## 2. Technology Stack

Use the following technologies:

| Component | Technology |
|---|---|
| Programming Language | Python |
| Backend Framework | FastAPI |
| Database | SQLite |
| ORM | SQLAlchemy |
| Database Migrations | Alembic |
| AI Framework | LangChain |
| Agent Orchestration | LangGraph |
| Frontend | Streamlit |
| Vector Database | ChromaDB or FAISS |
| Embeddings | Configurable embedding provider |
| LLM | Configurable LLM provider |
| API Communication | HTTP REST APIs |
| Authentication | JWT / OAuth2 |
| Password Hashing | Argon2 or bcrypt |
| Testing | Pytest |
| API Documentation | OpenAPI / Swagger |
| Containerization | Docker and Docker Compose |
| Logging | Python logging / structured logging |

Keep the LLM, embedding model, and vector database configurable through environment variables.

Do not tightly couple the application to a particular AI provider.

---

# 3. Module 1: Banking Backend APIs

Develop a dedicated FastAPI banking service responsible for all banking-related business operations.

The banking service must remain independent of the AI application.

The AI application must communicate with the banking service exclusively through HTTP API calls.

**Important architectural constraint:**
The AI application must never directly access the banking database, ORM models, or database repositories. All banking operations must go through authenticated banking REST APIs.

## 3.1 User Management

Develop APIs for:

- User registration.
- User login.
- Logout / token revocation.
- Get user profile.
- Update user profile.
- Change password.
- Manage authentication sessions.
- Retrieve user account information.

Each user must have isolated banking data.

## 3.2 Bank Account Management

Develop APIs for:

- Add bank account details.
- List linked bank accounts.
- Retrieve bank account details.
- Update bank account details.
- Delete or deactivate a linked bank account.
- Verify bank account details.
- Manage beneficiary accounts.

Capture appropriate fields, such as:

- Account holder name.
- Account number.
- IFSC code.
- Bank name.
- Branch name.
- Account type.
- Verification status.
- Created timestamp.

Never expose complete account numbers in API responses or logs. Use masking.

Beneficiary creation and modification must support additional verification and approval workflows.

## 3.3 Bank Transfers

Develop APIs for:

- Create a new bank transfer.
- Retrieve transfer details.
- List transaction history.
- Filter transactions by:
  - Date range.
  - Transaction type.
  - Amount range.
  - Transaction status.
  - Beneficiary.
  - Transaction reference.
- Retrieve transaction status.
- Cancel eligible pending transfers.
- Retrieve transfer limits.

Transfer operations must implement:

1. Beneficiary validation.
2. Available balance validation.
3. Transaction limit validation.
4. Duplicate transaction prevention.
5. Transaction authorization.
6. Transaction confirmation.
7. Transaction execution.
8. Transaction status tracking.
9. Audit logging.

Support transaction states such as:

- PENDING_APPROVAL
- AUTHORIZED
- PROCESSING
- COMPLETED
- FAILED
- CANCELLED

Use idempotency keys to prevent duplicate transfers.

A transfer must never be executed simply because an AI agent generated a request.

## 3.4 Loan Management

Develop APIs for:

- List pre-approved loan offers.
- Retrieve loan offer details.
- Check loan eligibility.
- Apply for a loan.
- Retrieve loan application status.
- List previous loan applications.
- Retrieve loan repayment details.
- List active loans.

Loan application fields may include:

- Loan type.
- Requested amount.
- Tenure.
- Interest rate.
- Employment information.
- Income information.
- Application status.

The backend must independently validate loan eligibility and applicable business rules.

## 3.5 Credit Card Management

Develop APIs for:

- List credit cards.
- Retrieve credit card details.
- Get outstanding balance.
- List credit card statements.
- Retrieve credit card bills.
- Make credit card bill payments.
- Retrieve payment history.
- Check payment status.

Implement payment validation and duplicate payment prevention.

Sensitive card information must never be exposed in plaintext.

---

# 4. Module 2: AI Banking Chat Application

Build an intelligent conversational banking assistant using LangChain and LangGraph.

The chat application must understand natural-language requests and determine whether they require:

1. Banking API operations.
2. Internal banking policy/document retrieval.
3. External internet research.
4. Human approval or authentication.
5. Rejection because the request is outside the supported banking domain.

## 4.1 AI Agent Architecture

Use LangGraph for agent orchestration.

Create specialized agents or logically separated agent nodes.

### A. Supervisor / Router Agent

Responsibilities:

- Understand the user's intent.
- Identify the appropriate banking operation.
- Route requests to specialized agents.
- Determine whether an API call is required.
- Determine whether internal document retrieval is required.
- Determine whether external internet research is appropriate.
- Identify requests requiring human approval.
- Maintain conversational context.
- Handle unsupported requests.

The supervisor must not independently execute financial transactions.

### B. Banking Operations Agent

Responsibilities:

- Handle banking-related queries.
- Use banking REST API tools.
- Retrieve linked bank accounts.
- Retrieve transaction history.
- Retrieve loan offers.
- Apply for loans.
- Retrieve credit card bills.
- Initiate eligible banking workflows.

All banking operations must use HTTP API integrations.

Never allow this agent to bypass the banking backend.

### C. Banking Policy RAG Agent

Responsibilities:

- Search internal banking documents.
- Retrieve relevant policy sections.
- Answer questions based on retrieved documents.
- Explain banking terms and procedures.
- Provide source references for retrieved information.
- Identify when sufficient information is unavailable.

Use a retrieval-augmented generation architecture.

Document processing pipeline:

1. Upload document.
2. Validate document format and size.
3. Extract document text.
4. Split text into chunks.
5. Generate embeddings.
6. Store vectors and metadata.
7. Retrieve relevant chunks during conversations.
8. Generate grounded responses with document citations.

Support PDF, DOCX, and TXT initially.

Include document metadata such as:

- Document ID.
- Document name.
- Document category.
- Version.
- Upload timestamp.
- Uploaded by.
- Active/inactive status.

### D. External Research Agent

Responsibilities:

- Answer general banking and financial information questions that are not covered by available banking APIs or internal documents.
- Use an approved internet search tool.
- Prefer reliable and authoritative sources.
- Include source URLs in responses.
- Clearly distinguish external information from official bank policy.

Restrictions:

- Never use internet research as a replacement for authenticated banking API data.
- Never use external sources to infer a user's account balance, transactions, loan eligibility, or private banking information.
- Do not execute financial transactions through external websites.
- Do not invent bank-specific policies.

### E. Response Agent

Responsibilities:

- Consolidate results from other agents.
- Generate clear and concise responses.
- Format transaction summaries.
- Explain errors and failed operations.
- Include relevant references and next steps.
- Avoid exposing sensitive information.

---

# 5. Banking Intent Classification and Routing

Implement a clear routing strategy.

Examples:

| User Query | Expected Routing |
|---|---|
| What is my account balance? | Banking Operations Agent |
| Show my last 10 transactions | Banking Operations Agent |
| Add a new beneficiary | Banking Agent + HITL |
| Transfer ₹5,000 to Rahul | Banking Agent + HITL |
| Show my pre-approved loans | Banking Operations Agent |
| Apply for a personal loan | Banking Operations Agent + Confirmation |
| What is the bank's loan policy? | Policy RAG Agent |
| What is the RBI repo rate? | External Research Agent |
| Explain Python decorators | Out-of-domain response |
| What are my credit card dues? | Banking Operations Agent |
| Pay my credit card bill | Banking Agent + HITL |

The router must prioritize authenticated banking APIs for customer-specific banking information.

If the required banking API does not exist, the system must not simulate the operation or invent banking data.

For unsupported banking operations, explain that the functionality is currently unavailable.

If the request is unrelated to banking and finance, politely inform the user that the assistant only supports banking and finance-related queries.

---

# 6. Module 3: Human-in-the-Loop (HITL)

Human-in-the-loop is a critical part of the application.

Use LangGraph interrupt/resume functionality to pause workflows when user authorization or confirmation is required.

The system must distinguish between:

- Information requests.
- Non-financial changes.
- Sensitive account changes.
- Financial transactions.
- High-risk operations.

## 6.1 Beneficiary Creation Workflow

Example:

User: Add a new beneficiary account.

Workflow:

1. Collect beneficiary details.
2. Validate required fields.
3. Display masked details for review.
4. Ask the user for explicit confirmation.
5. Require the configured authentication step.
6. Call the banking API.
7. Return the result.
8. Record the approval and audit information.

Do not create a beneficiary before approval.

## 6.2 Bank Transfer Workflow

Example:

User: Transfer ₹5,000 to Rahul.

Workflow:

1. Identify the beneficiary.
2. Retrieve beneficiary details using the banking API.
3. Validate available balance and transfer limits.
4. Prepare the transfer summary.
5. Display:
   - Beneficiary name.
   - Masked account number.
   - Transfer amount.
   - Applicable charges.
   - Total debit amount.
6. Ask for explicit confirmation.
7. Require transaction authentication, such as a transaction PIN or OTP.
8. Validate authorization through the banking backend.
9. Execute the transfer through the banking API.
10. Retrieve the transaction result.
11. Display transaction reference and status.

Critical rules:

- Confirmation and authentication are separate steps.
- Never ask users to share their normal banking password in chat.
- Never store passwords, PINs, or OTPs in conversation history, LLM prompts, vector databases, or logs.
- Authentication must be handled by a secure backend-controlled mechanism.
- An LLM must never generate, approve, or bypass authorization.
- A confirmed transaction must be bound to the exact beneficiary, amount, and transaction details displayed to the user.
- Any change to the amount or beneficiary requires fresh confirmation.
- Financial execution must be idempotent.

## 6.3 Loan Application Workflow

1. Retrieve available loan offers.
2. Display eligible options.
3. Collect missing application information.
4. Validate the application.
5. Display the application summary.
6. Obtain user confirmation.
7. Submit through the banking API.
8. Return the application reference.

## 6.4 LangGraph Workflow State

Design a typed state structure containing:

- user_id
- session_id
- conversation_id
- user_message
- intent
- agent_route
- messages
- tool_results
- pending_action
- approval_status
- authentication_status
- transaction_reference
- response

Do not place sensitive credentials or raw authentication secrets in graph state.

Use a secure checkpointer to persist resumable workflows.

Define expiration and cleanup rules for pending approvals.

---

# 7. Module 4: Streamlit Frontend

Develop a responsive Streamlit application with the following pages.

## 7.1 Authentication

- Login page.
- Signup page.
- Logout.
- Session management.
- Protected pages.
- Role-based access control.

## 7.2 Banking Chat

Features:

- Interactive chat interface.
- Conversation history.
- New conversation.
- Previous conversations.
- Display tool execution status.
- Display pending approval requests.
- Confirmation and rejection controls.
- Transaction summaries.
- Source citations for RAG and external research.
- Loading indicators and error handling.

Do not expose internal prompts, API credentials, authentication tokens, or sensitive tool payloads.

## 7.3 Chat History

Features:

- List previous conversations.
- Search conversations.
- Open previous conversations.
- Display messages with timestamps.
- Rename conversations.
- Delete conversations.

Maintain user-level data isolation.

## 7.4 Policy Document Management

Admin-only functionality:

- Upload policy documents.
- View uploaded documents.
- View processing status.
- Reprocess documents.
- Deactivate documents.
- Delete documents and their corresponding vectors.
- View metadata.
- Manage document versions.

## 7.5 Admin Dashboard

Admin functionality:

- Dashboard statistics.
- User management.
- User activation/deactivation.
- Role management.
- Banking transaction monitoring.
- Loan application monitoring.
- Chat conversation monitoring with sensitive-data masking.
- Policy document management.
- Audit log viewer.
- AI agent execution monitoring.
- System configuration.

Admin privileges must be enforced by the backend, not merely hidden in Streamlit.

---

# 8. Architectural Design Requirements

Use a modular monolith initially, with clearly separated application boundaries.

Suggested logical services:

1. Banking API Service.
2. AI Chat Service.
3. RAG Document Service.
4. Streamlit Frontend.

The banking service must own all banking business logic and financial data.

The AI service must own agent orchestration, conversations, RAG retrieval, and workflow state.

The frontend must communicate with backend services through APIs.

## Communication Architecture

- Streamlit → AI Chat API.
- Streamlit → Banking APIs for direct banking screens, where required.
- AI Chat Service → Banking APIs through HTTP clients.
- AI Chat Service → RAG retrieval service.
- AI Chat Service → External search tools when appropriate.

No direct database sharing between banking and AI services.

## Design Patterns

Apply suitable design patterns:

- Repository Pattern.
- Service Layer Pattern.
- Factory Pattern.
- Strategy Pattern.
- Adapter Pattern.
- Dependency Injection.
- Unit of Work where appropriate.
- State Machine Pattern.
- Tool Registry Pattern.

Avoid unnecessary abstractions.

---

# 9. Security and Banking Compliance Requirements

Security must be considered throughout the architecture.

Implement:

- JWT authentication.
- Password hashing.
- Role-based access control.
- User-level resource authorization.
- API authentication between services.
- HTTPS in production.
- Input validation.
- SQL injection protection.
- Rate limiting.
- Idempotency.
- Secure secrets management.
- Audit logging.
- Sensitive-data masking.
- Session expiration.
- Transaction authorization.
- Approval expiration.
- Secure document upload validation.
- Prompt injection protection.
- RAG document access controls.

Treat all user messages, uploaded documents, retrieved content, and external web content as untrusted input.

Never allow retrieved documents or user prompts to override system instructions or tool authorization rules.

The AI must not be trusted as a security boundary.

Every sensitive action must be validated by the banking backend independently.

SQLite is intended for local development and demonstration. Clearly document the migration path to PostgreSQL or another production-grade transactional database before real banking deployment.

Do not claim regulatory compliance without an actual compliance assessment.

---

# 10. API Design Standards

Follow REST API conventions.

Use versioned routes:

- /api/v1/auth
- /api/v1/users
- /api/v1/accounts
- /api/v1/beneficiaries
- /api/v1/transfers
- /api/v1/transactions
- /api/v1/loans
- /api/v1/credit-cards
- /api/v1/chat
- /api/v1/conversations
- /api/v1/documents
- /api/v1/admin
- /api/v1/audit-logs

For every API define:

- HTTP method.
- Endpoint.
- Authentication requirement.
- Authorization rules.
- Request schema.
- Response schema.
- Validation rules.
- Error responses.
- Business logic.
- Idempotency requirements, where applicable.

Use consistent error response formats.

Include pagination, sorting, and filtering where applicable.

---

# 11. Database Design

Prepare database schemas and entity relationships.

Banking database entities should include:

- User
- Role
- UserRole
- BankAccount
- Beneficiary
- BankTransaction
- TransferAuthorization
- LoanOffer
- LoanApplication
- CreditCard
- CreditCardStatement
- CreditCardPayment
- AuditLog
- RefreshToken / Session

AI application entities should include:

- ChatUserReference
- Conversation
- ChatMessage
- AgentExecution
- PendingApproval
- Document
- DocumentChunkMetadata
- WorkflowCheckpointMetadata

Ensure proper foreign keys, indexes, unique constraints, timestamps, and transaction boundaries.

Keep banking and AI application database ownership separate.

---

# 12. Testing Strategy

Create a comprehensive testing strategy.

### Unit Tests

- Banking business services.
- API validation.
- Transaction calculations.
- Loan eligibility.
- Agent routing.
- Intent classification.
- RAG retrieval.
- Approval workflows.

### Integration Tests

- Banking REST APIs.
- AI-to-banking API communication.
- Authentication.
- Database operations.
- Vector database operations.
- LangGraph workflow execution.

### Security Tests

- Unauthorized API access.
- Cross-user data access.
- Duplicate transaction attempts.
- Invalid approval attempts.
- Expired authentication.
- Prompt injection.
- Malicious uploaded documents.
- Sensitive-data leakage.

### AI Evaluation

- Intent classification accuracy.
- Tool selection accuracy.
- Tool argument validation.
- RAG retrieval relevance.
- Answer grounding.
- Out-of-domain rejection.
- HITL workflow correctness.

Never use real money or real financial accounts in automated tests. Use simulated banking data.

---

# 13. Development and Delivery Roadmap

Divide implementation into phases.

### Phase 1: Project Foundation
- Repository structure.
- Environment configuration.
- Docker Compose.
- FastAPI setup.
- SQLite and SQLAlchemy.
- Alembic.
- Logging.
- Shared configuration.

### Phase 2: Banking APIs
- Authentication.
- User management.
- Bank accounts.
- Beneficiaries.
- Transfers.
- Transactions.
- Loans.
- Credit cards.

### Phase 3: AI Infrastructure
- LLM integration.
- LangChain configuration.
- LangGraph setup.
- Agent state.
- Supervisor agent.
- Tool registry.
- Banking API client.

### Phase 4: Banking AI Agents
- Banking agent.
- Policy RAG agent.
- External research agent.
- Response agent.
- Intent classification.
- Agent routing.

### Phase 5: Human-in-the-Loop
- Beneficiary approval.
- Transfer confirmation.
- Transaction authentication.
- Loan application confirmation.
- Workflow persistence.
- Resume and rejection handling.

### Phase 6: Frontend
- Authentication.
- Banking chat.
- Chat history.
- Document upload.
- Admin dashboard.

### Phase 7: Banking System Improvements
- Auto-create bank account on signup.
- Auto-create card details on signup.
- Provision loan offers (home, car, personal loan) on signup.
- User dashboard displaying bank, card, and loan details post-login.

### Phase 8: Transaction PIN Management & Setup
- Option to provide transaction PIN during user creation/registration.
- Option to regenerate/reset transaction PIN using password verification.
- Backend PIN schemas, auth/user endpoints, and security auditing.
- Frontend registration form PIN fields and PIN regeneration settings view.
- Comprehensive unit and integration test coverage.

### Phase 9: Testing and Hardening
- Unit tests.
- Integration tests.
- Security tests.
- AI evaluations.
- Performance testing.
- Error handling.

### Phase 10: Deployment and Documentation
- Docker Compose.
- Environment setup.
- API documentation.
- Architecture documentation.
- Deployment guide.
- Troubleshooting guide.

---

# 14. Expected Architecture Deliverables

Before implementation, generate the following documentation:

1. `README.md` – Project overview and setup.
2. `architecture.md` – High-level system architecture.
3. `low_level_design.md` – Module-level design and class responsibilities.
4. `database_design.md` – ERD and database schema.
5. `api_specification.md` – Complete API contracts.
6. `agent_architecture.md` – Agent responsibilities and LangGraph workflows.
7. `rag_design.md` – Document ingestion, chunking, embedding, and retrieval.
8. `hitl_workflows.md` – Approval and authentication workflows.
9. `security.md` – Security architecture and controls.
10. `testing.md` – Testing strategy.
11. `scope.md` – Functional and non-functional scope.
12. `TODO.md` – Detailed development tasks.
13. `CHANGELOG.md` – Change tracking.
14. `CONTRIBUTING.md` – Development guidelines.
15. `requirements.md` – Functional and technical requirements.
16. `.env.example` – Environment variable template.
17. `docker-compose.yml` – Local development environment.

---

# 15. Expected AI Response and Working Methodology

Follow these instructions strictly:

**Step 1: Requirement Analysis**
- Identify functional requirements.
- Identify non-functional requirements.
- Identify assumptions.
- Identify missing information.
- Identify security-sensitive workflows.

**Step 2: Architecture Design**
- Propose the complete architecture.
- Explain service boundaries.
- Explain API communication.
- Explain agent orchestration.
- Explain database ownership.
- Explain HITL workflows.

**Step 3: Database and API Design**
- Define entities and relationships.
- Define API endpoints.
- Provide request and response examples.
- Explain validation and authorization.

**Step 4: Agent Design**
- Define each agent's responsibility.
- Define LangGraph nodes and edges.
- Define tools and tool schemas.
- Define routing conditions.
- Define workflow interruption and resumption.

**Step 5: Development Planning**
- Break down the project into phases.
- Create granular development tasks.
- Define task dependencies.
- Define acceptance criteria.
- Identify deliverables for each task.

**Step 6: Implementation**
Only start implementation after architecture and requirements have been reviewed.

When implementing:
- Follow the approved architecture.
- Write modular, typed, maintainable Python code.
- Include docstrings and meaningful comments.
- Add error handling and logging.
- Add tests for each major component.
- Avoid hardcoded credentials.
- Avoid unnecessary complexity.
- Update documentation when functionality changes.

**Important Rules:**

1. Never connect the AI application directly to the banking database.
2. Always use authenticated REST APIs for banking operations.
3. Never allow an AI agent to independently authorize financial transactions.
4. Always require explicit confirmation and backend-controlled authentication for sensitive financial operations.
5. Never expose passwords, PINs, OTPs, or complete account/card details to an LLM.
6. Never fabricate transaction, account, or loan information.
7. Never use external internet research as a substitute for private banking APIs.
8. Never execute an operation when the required API or authorization mechanism is unavailable.
9. Always maintain audit trails for sensitive operations.
10. Treat SQLite as a local development database, not a production banking database.

**Your first response must contain:**

- Requirement analysis.
- Identified assumptions.
- Recommended architecture.
- System component diagram.
- Proposed folder structure.
- Core database entities.
- Banking API module breakdown.
- LangGraph agent architecture.
- Human-in-the-loop workflows.
- Security considerations.
- Development phases and granular task breakdown.
- Open questions requiring clarification.

Do not generate the entire application code in the first response. Work incrementally, one module at a time, and ensure every module follows the approved architecture.