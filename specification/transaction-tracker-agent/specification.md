# Specification: transaction-tracker-agent

> **Guidelines**: Read [guidelines.md](../guidelines.md) and [guidelines-agent.md](../guidelines-agent.md) before executing ANY tasks below. Follow all constraints described there throughout execution.

## Basic Setup

- [ ] Read the project input (`product-requirements-document.md`, `intent.md`)
- [ ] Bootstrap agent code in `assets/transaction-tracker-agent/` using skill `sap-agent-bootstrap` (invoke from inside `assets/transaction-tracker-agent/`, use copy commands — do NOT create files manually)
- [ ] Install dependencies, validate the agent starts and responds at `/.well-known/agent.json`

## Agent Identity & System Prompt

- [ ] Set agent name to `Transaction Tracker Agent` and description to `Retrieves transaction details and tenant information from the Transaction Tracker database by document ID`
- [ ] Configure system prompt in `app/agent.py` via `@prompt_section` decorator with the following instructions:
  - You are an AI agent that retrieves transaction details and tenant information from the Transaction Tracker database.
  - Use `get_transaction_details` when asked for transaction information given a document ID.
  - Use `get_tenant_id` when asked for the tenant where a transaction was processed.
  - Present results in a readable, structured format with field labels and values.
  - Respond with a clear "not found" message if the document ID does not exist.
  - Never hallucinate transaction data — only return what the tools provide.
  - Always inform the user which document ID was used in the lookup.

## Tool Implementation

- [ ] Create `app/tools/get_transaction_details.py`:
  - Implement `get_transaction_details(document_id: str) -> dict` as a LangChain `StructuredTool`
  - The tool must query the Transaction Tracker database for all fields associated with the given document ID
  - Return a dictionary of transaction fields and their values, or an empty dict / `None` if not found
  - Add a clear docstring describing the tool's purpose and parameters
  - **Do NOT mock database connectivity in tool code** — use an injectable data-access layer so tests can patch it

- [ ] Create `app/tools/get_tenant_id.py`:
  - Implement `get_tenant_id(document_id: str) -> dict` as a LangChain `StructuredTool`
  - The tool must query the Transaction Tracker database for the tenant identifier associated with the given document ID
  - Return a dictionary with a `tenant_id` field, or an empty dict / `None` if not found
  - Add a clear docstring describing the tool's purpose and parameters
  - **Do NOT mock database connectivity in tool code** — use an injectable data-access layer so tests can patch it

- [ ] Create `app/tools/__init__.py` exporting both tools
- [ ] Register both tools in the agent's tool list in `app/agent.py` (loaded via `_load_tools()` pattern from guidelines)
- [ ] Update `requirements.txt` with any new dependencies (e.g. database driver if needed)

## Agent Behaviour

- [ ] Verify the agent correctly routes `get_transaction_details` queries when the user asks for transaction information (e.g. "What are the details for document ID TXN-001?")
- [ ] Verify the agent correctly routes `get_tenant_id` queries when the user asks for tenant information (e.g. "Which tenant processed document TXN-001?")
- [ ] Verify the agent formats all tool responses with labelled fields and values (e.g. `Document ID: TXN-001 \n Status: Completed \n Amount: 1000`)
- [ ] Verify the agent returns a clear "not found" message when a document ID does not exist (e.g. "No transaction found for document ID: TXN-999")
- [ ] Verify the agent always states the document ID used in every response
- [ ] Verify the agent never generates transaction field values not returned by a tool

## Business Step Instrumentation (Milestones)

- [ ] Instrument **M1 — User Query Received**: emit `M1.achieved: user query received with document_id={document_id}` when a document ID is extracted from the user query; emit `M1.missed: no document_id detected in user query` when none is found. Wrap in an OpenTelemetry span `@tracer.start_as_current_span("m1_user_query_received")`
- [ ] Instrument **M2 — Tool Selected**: emit `M2.achieved: tool selected={tool_name} for document_id={document_id}` when the agent selects a tool; emit `M2.missed: could not determine tool for query, document_id={document_id}` on fallback. Wrap in an OpenTelemetry span `@tracer.start_as_current_span("m2_tool_selected")`
- [ ] Instrument **M3 — Data Retrieved**: emit `M3.achieved: data retrieved for document_id={document_id}, tool={tool_name}` on non-empty tool response; emit `M3.missed: tool returned no data or error for document_id={document_id}, tool={tool_name}` on empty/error result. Wrap in an OpenTelemetry span `@tracer.start_as_current_span("m3_data_retrieved")`
- [ ] Instrument **M4 — Response Formatted**: emit `M4.achieved: response formatted for document_id={document_id}` after the agent composes its reply; emit `M4.missed: response formatting failed for document_id={document_id}` on failure. Wrap in an OpenTelemetry span `@tracer.start_as_current_span("m4_response_formatted")`
- [ ] Instrument **M5 — Document ID Confirmed in Response**: emit `M5.achieved: document_id echoed in response, document_id={document_id}` when the document ID appears in the final response; emit `M5.missed: document_id not present in agent response, document_id={document_id}` when it is absent. Wrap in an OpenTelemetry span `@tracer.start_as_current_span("m5_document_id_confirmed")`
- [ ] Verify `auto_instrument()` is called at top of `main.py` before any AI framework imports

## Mock Configuration

- [ ] Generate `mcp-mock.json` using the `mcp-mock-config` skill to provide deterministic tool responses for tests:
  - `get_transaction_details` mock: return a sample transaction dict (e.g. `{"document_id": "TXN-001", "status": "Completed", "amount": "1000.00", "currency": "USD", "created_at": "2026-01-15T10:00:00Z"}`)
  - `get_transaction_details` not-found mock: return `{}` or `null` for a non-existent document ID (e.g. `TXN-999`)
  - `get_tenant_id` mock: return `{"tenant_id": "TENANT-A"}` for a valid document ID
  - `get_tenant_id` not-found mock: return `{}` or `null` for a non-existent document ID

## Testing

- [ ] `conftest.py` only sets `IBD_TESTING=true` — this causes the agent to run with mock tool results during tests
- [ ] Write unit test for `get_transaction_details` tool in `assets/transaction-tracker-agent/tests/test_get_transaction_details.py`:
  - Test: valid document ID returns expected transaction fields
  - Test: non-existent document ID returns empty/null
  - Run immediately after writing
- [ ] Write unit test for `get_tenant_id` tool in `assets/transaction-tracker-agent/tests/test_get_tenant_id.py`:
  - Test: valid document ID returns expected tenant ID
  - Test: non-existent document ID returns empty/null
  - Run immediately after writing
- [ ] Write one integration test in `assets/transaction-tracker-agent/tests/test_integration.py` executing an end-to-end agent flow with real LLM:
  - Test: agent correctly retrieves and formats transaction details for a valid document ID
  - Test: agent returns a "not found" message for a non-existent document ID
  - Test: agent response always includes the document ID used
  - Mock `get_transaction_details` and `get_tenant_id` data sources; never mock the LLM
- [ ] Run `pytest` from `assets/transaction-tracker-agent/` (no args) — fix any failures before proceeding
- [ ] Verify `assets/transaction-tracker-agent/app/agent.py` has exactly 3 decorated functions: `@agent_model`, `@agent_config`, `@prompt_section` — run `grep -c "^@agent_model\|^@agent_config\|^@prompt_section" assets/transaction-tracker-agent/app/agent.py` and confirm it returns 3
- [ ] Run `pytest` again from `assets/transaction-tracker-agent/` (no args) to generate final `test_report.json`
- [ ] Verify `test_report.json` exists in `assets/transaction-tracker-agent/` — if not, run pytest again

## Agent Evaluation

- [ ] Invoke `sap-aeval-generate-tool-schema` from `assets/transaction-tracker-agent/` to generate `tools.json`
- [ ] Invoke `sap-aeval-generate-testcase` from `assets/transaction-tracker-agent/` passing the PRD and `tools.json`; review generated test cases and replace all placeholder values with realistic document IDs and expected transaction data
