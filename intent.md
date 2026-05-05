# Transaction Tracker Agent

AI agent that retrieves transaction details and tenant information from a custom Transaction Tracker database.

## Business challenge

Operations/support staff and technical/IT teams need a conversational interface to quickly look up transaction status and tenant context from a custom-built Transaction Tracker database using document IDs — without having to query the database directly or navigate multiple tools. The agent must return only verified data from its tools, clearly indicate when a document is not found, and always disclose which document ID was used for the lookup.

## Key Milestones

1. **User Query Received** — User submits a natural language request referencing a document ID.
2. **Tool Selected** — Agent determines whether to invoke `get_transaction_details`, `get_tenant_id`, or both based on intent.
3. **Data Retrieved** — Tool(s) execute against the Transaction Tracker database and return structured results.
4. **Response Formatted** — Agent presents results with field labels and values in a readable layout, or returns a clear "not found" message.
5. **Document ID Confirmed** — Agent always echoes the document ID used in the lookup within its response.

## Business Architecture (RBA)

### End-to-End Process

Lead to Cash for Leasing / Finance — Transaction Monitoring (closest RBA mapping; custom Transaction Tracker is not covered by a standard SAP E2E process)

### Process Hierarchy

```
Corporate (Finance & IT Management)
└── IT Management / Operations
    └── Transaction Monitoring
        └── Look up transaction by document ID
        └── Identify tenant for a transaction
```

### Summary

The challenge maps to an operational support capability within IT Management — specifically transaction lookup and tenant resolution — which is not covered by a standard SAP RBA sub-process. The Transaction Tracker is a custom-built system requiring a custom AI agent to provide a natural-language query interface over its data.

## Fit Gap Analysis

| Requirement (business)                              | Standard asset(s) found                        | API ORD ID                  | MCP Server ORD ID | Gap?  | Notes / assumptions                                              |
| --------------------------------------------------- | ---------------------------------------------- | --------------------------- | ----------------- | ----- | ---------------------------------------------------------------- |
| Retrieve transaction details by document ID         | Transaction Monitoring API, Transaction Batches | `bizmonservice_v2`          | —                 | Yes   | No MCP server found; custom `get_transaction_details` tool required |
| Retrieve tenant ID for a given transaction          | Tenant Management Service, Tenant Configuration | `TenantAPI`, `Tenantconfig_API` | —             | Yes   | No MCP server found; custom `get_tenant_id` tool required        |
| Natural language interface over transaction data    | None                                           | —                           | —                 | Yes   | Custom AI agent needed                                           |
| Structured result formatting with field labels      | None                                           | —                           | —                 | Yes   | Agent instruction / prompt engineering                           |
| Not-found handling and document ID echo             | None                                           | —                           | —                 | Yes   | Agent instruction / prompt engineering                           |
| Multi-channel deployment (Joule, BTP, standalone)   | SAP App Foundation A2A agent runtime           | —                           | —                 | No    | A2A protocol supports Joule integration and standalone deployment |

### Key findings

- The Transaction Tracker is a custom-built database; no standard SAP product covers it out of the box.
- Two custom tools are pre-defined: `get_transaction_details` (document ID → transaction data) and `get_tenant_id` (document ID → tenant).
- No MCP servers were found for the Transaction Monitoring or Tenant Management APIs, confirming the need for custom tool implementations.
- The agent must be built as a pro-code Python A2A agent on SAP App Foundation to satisfy all three deployment targets (Joule, BTP embedded, standalone).
- Agent behavior (formatting, not-found messages, document ID echo, no hallucination) must be enforced via system prompt / agent instructions.
- The LeanIX landscape shows no existing application covering this Transaction Tracker capability — it is a greenfield AI agent build.

## Recommendations

### Transaction Tracker AI Agent on SAP App Foundation

#### Executive Summary

Build a pro-code Python A2A agent on SAP App Foundation that wraps the two pre-defined tools (`get_transaction_details`, `get_tenant_id`) and exposes a conversational interface for operations and IT teams to look up transaction status and tenant context by document ID.

#### Recommended Solution

A Python-based A2A agent deployed on SAP App Foundation runtime, implementing:
- `get_transaction_details` tool: accepts a document ID, queries the custom Transaction Tracker database, returns transaction fields.
- `get_tenant_id` tool: accepts a document ID, queries the Transaction Tracker database, returns the processing tenant.
- Agent instructions enforcing: structured output with field labels, clear "not found" messaging, always echo the document ID used, no data hallucination.
- OpenTelemetry instrumentation for observability.
- A2A protocol compatibility enabling integration with SAP Joule, embedding in SAP BTP applications, and standalone operation.

#### Affected User Roles

- Operations / support staff (transaction status lookup)
- Technical / IT teams (transaction debugging, multi-tenant issue resolution)

#### Recommended solution category

AI Agent
