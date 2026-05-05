"""
Transaction Tracker Agent - Core Agent Implementation

This module implements the AI agent "brain" using LangGraph, a framework for
building stateful, multi-step applications with LLMs.

Key Concepts for New Developers:
  1. **Agent** = LLM + Tools + State Machine (workflow)
  2. **LangGraph** = Defines the agent's workflow as a graph of nodes
  3. **Tools** = Functions the agent can call to retrieve data
  4. **State** = Conversation history passed through the workflow
  5. **Milestones** = Checkpoints we track for monitoring

Architecture:
  User Query → Extract Document ID → Call LLM →
  LLM Decides → Call Tool → Format Response → Return to User

For more details, see ARCHITECTURE.md
"""
import logging
import re
from dataclasses import dataclass
from typing import AsyncGenerator, Literal, Optional

# LangChain Core - Message types for conversations
from langchain_core.messages import HumanMessage, SystemMessage

# LangGraph - State machine framework for agent workflows
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode  # Automatically executes tools

# OpenTelemetry - Observability/tracing
from opentelemetry import trace

# SAP Cloud SDK decorators for agent configuration
# Fallback to stub if SDK not installed (local development)
try:
    from sap_cloud_sdk.agent_decorators import agent_config, agent_model, prompt_section
except ImportError:
    from sap_cloud_sdk_stub import agent_config, agent_model, prompt_section

# MCP Tools - Loads tools from MCP protocol or mock data
from mcp_tools import get_mcp_tools

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)  # For distributed tracing spans


# ============================================================================
# Document ID Extraction
# ============================================================================
# Regex to extract a document ID from a user query (e.g. TXN-001, DOC-42, INV-2024-001)
# Pattern explanation:
#   \b         = Word boundary
#   [A-Z]{2,10} = 2-10 uppercase letters (e.g., "TXN", "DOC", "INV")
#   -          = Literal hyphen
#   [\w-]+     = One or more word characters or hyphens
#   \b         = Word boundary
_DOCUMENT_ID_PATTERN = re.compile(r"\b([A-Z]{2,10}-[\w-]+)\b", re.IGNORECASE)


def _extract_document_id(query: str) -> Optional[str]:
    """Return the first document-ID-like token found in *query*, or None."""
    match = _DOCUMENT_ID_PATTERN.search(query)
    return match.group(1) if match else None


@agent_model(
    key="config.model",
    label="LLM Model",
    description="The language model powering this agent",
)
def get_model_name() -> str:
    import os
    return os.environ.get("LITELLM_MODEL", "sap/anthropic--claude-4.5-sonnet")


@agent_config(
    key="config.temperature",
    label="LLM Temperature",
    description="Controls randomness of responses (0.0 = deterministic, 1.0 = creative)",
)
def get_temperature() -> float:
    return 0.0


@prompt_section(
    key="prompts.system",
    label="System Prompt",
    description="The full system prompt defining the agent's role and behavior",
    validation={"format": "markdown", "max_length": 5000},
)
def get_system_prompt() -> str:
    return """You are an AI agent that retrieves transaction details and tenant information from the Transaction Tracker database.

Use get_transaction_details when asked for transaction information given a document ID.
Use get_tenant_id when asked for the tenant where a transaction was processed.

Present results in a readable, structured format with field labels and values.
Respond with a clear "not found" message if the document ID does not exist — do not invent or guess any data.
Never hallucinate transaction data — only return what the tools provide.
Always inform the user which document ID was used in the lookup."""


@dataclass
class AgentResponse:
    status: Literal["input_required", "completed", "error"]
    message: str


class SampleAgent:
    SUPPORTED_CONTENT_TYPES = ["text", "text/plain"]

    def __init__(self):
        """
        Initialize the Transaction Tracker Agent.

        Sets up the LLM (Language Model) that powers the agent's decision-making.

        Configuration:
          - Model: Configurable via LITELLM_MODEL env var (default: Claude Sonnet 4.6)
          - Temperature: 0.0 for deterministic responses (no randomness)
          - API Base: LiteLLM proxy URL for routing to Claude API

        The LLM is the "brain" that:
          1. Reads user queries
          2. Decides which tool to call
          3. Formats responses
        """
        import os
        from langchain_litellm import ChatLiteLLM

        # Get LiteLLM proxy configuration from environment
        api_base = os.environ.get("LITELLM_API_BASE")  # e.g., http://localhost:6655
        api_key = os.environ.get("LITELLM_API_KEY")    # Proxy API key

        # Initialize ChatLiteLLM (routes to Claude via proxy)
        if api_base:
            # Use proxy configuration for local development
            self.llm = ChatLiteLLM(
                model=get_model_name(),           # e.g., "anthropic/claude-sonnet-4.6"
                temperature=get_temperature(),    # 0.0 = deterministic
                api_base=api_base,                # LiteLLM proxy URL
                api_key=api_key                   # Proxy authentication
            )
        else:
            # Direct API access (production)
            self.llm = ChatLiteLLM(
                model=get_model_name(),
                temperature=get_temperature()
            )

        # Graph will be lazily built on first use (see _get_graph)
        self._graph = None

    def _build_graph(self, tools):
        """
        Build the LangGraph workflow (state machine) for the agent.

        What is a Graph?
          A graph defines the agent's workflow as a series of steps (nodes)
          connected by transitions (edges). Think of it like a flowchart.

        Our Workflow:
          ┌───────┐
          │ START │
          └───┬───┘
              ↓
          ┌───────────┐
          │   model   │ ← LLM decides what to do
          └─────┬─────┘
                ↓
          Should call tools?
           /          \
          Yes         No
           ↓           ↓
        ┌──────┐    ┌─────┐
        │tools │    │ END │
        └──┬───┘    └─────┘
           ↓
        (loops back to model to format results)

        Args:
            tools: List of LangChain tools (get_transaction_details, get_tenant_id)

        Returns:
            Compiled LangGraph workflow
        """
        # Bind tools to LLM so it knows what tools are available
        # The LLM reads tool descriptions to decide which to call
        llm_with_tools = self.llm.bind_tools(tools)

        # ToolNode automatically executes tools when LLM requests them
        # You don't write tool execution code - ToolNode handles it!
        tool_node = ToolNode(tools)

        def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
            """
            Decide the next step based on LLM's response.

            State Machine Logic:
              - If LLM wants to call tools → go to "tools" node
              - If LLM has final answer → go to END

            Args:
                state: Current conversation state (list of messages)

            Returns:
                "tools" if LLM requested tool calls, "__end__" otherwise
            """
            last = state["messages"][-1]
            if hasattr(last, "tool_calls") and last.tool_calls:
                return "tools"  # LLM wants to use a tool
            return "__end__"    # LLM has final response

        async def call_model(state: MessagesState):
            """
            Call the LLM with current conversation state.

            Args:
                state: MessagesState containing conversation history

            Returns:
                Updated state with LLM's response added
            """
            response = await llm_with_tools.ainvoke(state["messages"])
            return {"messages": [response]}

        # Build the graph structure
        builder = StateGraph(MessagesState)

        # Add nodes (steps in the workflow)
        builder.add_node("model", call_model)   # LLM thinking step
        builder.add_node("tools", tool_node)    # Tool execution step

        # Add edges (transitions between steps)
        builder.add_edge(START, "model")  # Start → call LLM first

        # Conditional edge: LLM decides next step
        builder.add_conditional_edges(
            "model",           # From the model node
            should_continue,   # Decision function
            {
                "tools": "tools",      # If tools needed, go to tools node
                "__end__": END         # If done, go to END
            }
        )

        # After tools run, always go back to model for formatting
        builder.add_edge("tools", "model")

        # Compile the graph into executable workflow
        return builder.compile()

    async def _get_graph(self):
        """
        Get or create the agent's workflow graph.

        Lazy Loading:
          The graph is built once on first use and cached for subsequent requests.
          This improves performance - we don't rebuild the graph for every query.

        Returns:
            Compiled LangGraph workflow
        """
        if self._graph is None:
            # Load tools from MCP (Model Context Protocol) or mock data
            tools = await get_mcp_tools()
            logger.info("Building graph with %d tool(s): %s", len(tools), [t.name for t in tools])

            # Build and cache the graph
            self._graph = self._build_graph(tools)

        return self._graph

    # ============================================================================
    # Step Instrumentation - Observability Checkpoints
    # ============================================================================
    #
    # What are Steps?
    #   Steps are checkpoints we track throughout the agent's workflow
    #   to monitor performance and diagnose issues.
    #
    # Why Track Steps?
    #   - Debugging: See exactly where the agent succeeds or fails
    #   - Performance: Measure time spent at each stage
    #   - Analytics: Understand user behavior patterns
    #   - Compliance: Audit trail of agent actions
    #
    # Our 5 Steps:
    #   Step 1: User query received (document ID extracted?)
    #   Step 2: Tool selected (which tool did LLM choose?)
    #   Step 3: Data retrieved (did tool return data?)
    #   Step 4: Response formatted (did LLM format the response?)
    #   Step 5: Document ID confirmed (is doc ID in final response?)
    #
    # Each step logs success or "missed" state for monitoring.
    # ============================================================================

    @tracer.start_as_current_span("step1_user_query_received")
    def _step1_user_query_received(self, query: str) -> Optional[str]:
        """
        Step 1: Extract document ID from user query.

        Why track this?
          Many queries should contain a document ID (e.g., "Show me TXN-001").
          If we can't extract one, it might indicate:
            - User entered invalid format
            - Query is too vague
            - Regex pattern needs adjustment

        Args:
            query: User's natural language query

        Returns:
            Extracted document ID (e.g., "TXN-001") or None if not found
        """
        document_id = _extract_document_id(query)
        if document_id:
            logger.info("Step1.achieved: user query received with document_id=%s", document_id)
        else:
            logger.warning("Step1.missed: no document_id detected in user query")
        return document_id

    @tracer.start_as_current_span("step2_tool_selected")
    def _step2_tool_selected(self, result: dict, document_id: Optional[str]) -> Optional[str]:
        """
        Step 2: Verify that LLM selected a tool.

        Why track this?
          The LLM should call a tool to retrieve data. If it doesn't:
            - The query might be conversational ("What can you do?")
            - The LLM might be confused about which tool to use
            - Tool descriptions might need improvement

        Args:
            result: Graph execution result containing messages
            document_id: Extracted document ID from Step 1

        Returns:
            Name of selected tool (e.g., "get_transaction_details") or None
        """
        messages = result.get("messages", [])

        # Search backwards through messages to find tool calls
        for msg in reversed(messages):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                # Extract tool name (handles both dict and object formats)
                tool_name = (
                    msg.tool_calls[0].get("name")
                    if isinstance(msg.tool_calls[0], dict)
                    else msg.tool_calls[0].name
                )
                logger.info("Step2.achieved: tool selected=%s for document_id=%s", tool_name, document_id)
                return tool_name

        logger.warning("Step2.missed: could not determine tool for query, document_id=%s", document_id)
        return None

    @tracer.start_as_current_span("step3_data_retrieved")
    def _step3_data_retrieved(self, result: dict, document_id: Optional[str], tool_name: Optional[str]):
        """
        Step 3: Verify that tool returned data.

        Why track this?
          Tools should return data (or empty dict if not found). If no data:
            - Document ID doesn't exist (legitimate not-found)
            - API/database error occurred
            - Tool implementation has a bug

        This helps distinguish between "not found" and "error" scenarios.

        Args:
            result: Graph execution result containing messages
            document_id: Document ID from Step 1
            tool_name: Tool name from Step 2
        """
        messages = result.get("messages", [])

        # Look for ToolMessage in conversation
        for msg in messages:
            if hasattr(msg, "type") and msg.type == "tool" and msg.content:
                logger.info(
                    "Step3.achieved: data retrieved for document_id=%s, tool=%s",
                    document_id,
                    tool_name,
                )
                return

        # No tool message found or empty content
        logger.warning(
            "Step3.missed: tool returned no data or error for document_id=%s, tool=%s",
            document_id,
            tool_name,
        )

    @tracer.start_as_current_span("step4_response_formatted")
    def _step4_response_formatted(self, response: str, document_id: Optional[str]):
        """
        Step 4: Verify that LLM formatted a response.

        Why track this?
          The LLM should take tool results and format them nicely for the user.
          If response is empty:
            - LLM failed to process tool results
            - Unexpected error occurred
            - Token limit reached (rare)

        Args:
            response: Final response content from LLM
            document_id: Document ID from Step 1
        """
        if response:
            logger.info("Step4.achieved: response formatted for document_id=%s", document_id)
        else:
            logger.warning("Step4.missed: response formatting failed for document_id=%s", document_id)

    @tracer.start_as_current_span("step5_document_id_confirmed")
    def _step5_document_id_confirmed(self, response: str, document_id: Optional[str]):
        """
        Step 5: Verify document ID appears in final response.

        Why track this?
          Our system prompt instructs the LLM to echo the document ID back
          to the user for confirmation. This ensures:
            - User knows which transaction was retrieved
            - No confusion about which document ID was used
            - Compliance with "confirm what you did" principle

        If missed:
          - LLM didn't follow system prompt instructions
          - Response is a "not found" message (might not include ID)
          - System prompt needs to be more explicit

        Args:
            response: Final response content from LLM
            document_id: Document ID from Step 1
        """
        if document_id and document_id.lower() in response.lower():
            logger.info(
                "Step5.achieved: document_id echoed in response, document_id=%s", document_id
            )
        else:
            logger.warning(
                "Step5.missed: document_id not present in agent response, document_id=%s",
                document_id,
            )

    # ============================================================================
    # Core Execution Methods
    # ============================================================================
    #
    # The agent has two execution interfaces:
    #   1. stream() - Returns results incrementally (for real-time UX)
    #   2. invoke() - Returns final result only (simpler, but waits for completion)
    #
    # Both follow the same workflow:
    #   User Query → Extract ID (Step 1) → Run Graph → Tool Selection (Step 2) →
    #   Data Retrieved (Step 3) → Format Response (Step 4) → Confirm ID (Step 5) → Return
    # ============================================================================

    async def stream(self, query: str, context_id: str) -> AsyncGenerator[dict, None]:
        """
        Execute agent workflow and stream results incrementally.

        Streaming allows the UI to show progress updates in real-time:
          - "Processing..." while agent thinks
          - Final response when complete
          - Error message if something fails

        This is used by the A2A protocol for responsive user experience.

        Args:
            query: User's natural language query (e.g., "Show me TXN-001")
            context_id: Conversation context identifier (for multi-turn)

        Yields:
            dict: Progress updates with structure:
              - is_task_complete: bool (True when done)
              - require_user_input: bool (True if needs clarification)
              - content: str (status message or final response)
        """
        # Yield initial "working" status
        yield {
            "is_task_complete": False,
            "require_user_input": False,
            "content": "Processing...",
        }

        try:
            # Step 1: Extract document ID from query
            document_id = self._step1_user_query_received(query)

            # Build conversation with system prompt + user query
            messages = [
                SystemMessage(content=get_system_prompt()),
                HumanMessage(content=query),
            ]

            # Execute the LangGraph workflow
            # This runs: LLM → Tool Selection → Tool Execution → Response Formatting
            result = await (await self._get_graph()).ainvoke({"messages": messages})

            # Track steps for observability
            tool_name = self._step2_tool_selected(result, document_id)
            self._step3_data_retrieved(result, document_id, tool_name)

            # Extract final response from last message
            response = result["messages"][-1].content

            # Verify response quality
            self._step4_response_formatted(response, document_id)
            self._step5_document_id_confirmed(response, document_id)

            # Yield final result
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": response,
            }

        except Exception as e:
            # Catch any errors and return them to user gracefully
            logger.error("Agent stream error: %s", e, exc_info=True)
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": f"Error: {e}",
            }

    async def invoke(self, query: str, context_id: str) -> AgentResponse:
        """
        Execute agent workflow and return final result.

        Simpler alternative to stream() - waits for completion and returns
        the final response in one step. No intermediate progress updates.

        Use this when:
          - You don't need streaming
          - Batch processing
          - Testing/scripting

        Args:
            query: User's natural language query
            context_id: Conversation context identifier

        Returns:
            AgentResponse with:
              - status: "completed" or "error"
              - message: Final response text or error message
        """
        try:
            # Same workflow as stream(), but returns result directly
            document_id = self._step1_user_query_received(query)

            messages = [
                SystemMessage(content=get_system_prompt()),
                HumanMessage(content=query),
            ]
            result = await (await self._get_graph()).ainvoke({"messages": messages})

            # Track steps
            tool_name = self._step2_tool_selected(result, document_id)
            self._step3_data_retrieved(result, document_id, tool_name)

            response = result["messages"][-1].content

            self._step4_response_formatted(response, document_id)
            self._step5_document_id_confirmed(response, document_id)

            return AgentResponse(status="completed", message=response)

        except Exception as e:
            logger.error("Agent invoke error: %s", e, exc_info=True)
            return AgentResponse(status="error", message=f"Error: {e}")
