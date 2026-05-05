import logging
import re
from dataclasses import dataclass
from typing import AsyncGenerator, Literal, Optional

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode
from opentelemetry import trace
from sap_cloud_sdk.agent_decorators import agent_config, agent_model, prompt_section

from mcp_tools import get_mcp_tools

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


def _build_mock_llm():
    """Return a lightweight mock LLM for IBD_TESTING mode.

    The mock interprets the last HumanMessage and routes to an appropriate tool
    or returns a fixed text response — no real LLM calls are made.
    """
    from unittest.mock import AsyncMock, MagicMock

    import re as _re
    from langchain_core.messages import AIMessage

    _DOC_PAT = _re.compile(r"\b([A-Z]{2,10}-[\w-]+)\b", _re.IGNORECASE)

    async def _ainvoke(messages, **_kwargs):
        # Extract text from the last human message
        last = messages[-1] if messages else None
        text = getattr(last, "content", "") or ""

        # If there are already tool results in the conversation, return a summary
        from langchain_core.messages import ToolMessage as _TM
        tool_messages = [m for m in messages if isinstance(m, _TM)]
        if tool_messages:
            doc_match = _DOC_PAT.search(text) if not tool_messages else None
            # Summarise tool outputs
            parts = []
            for tm in tool_messages:
                try:
                    import json as _json
                    data = _json.loads(tm.content)
                    if data:
                        doc_id = data.get("document_id") or _DOC_PAT.search(text)
                        if doc_id:
                            doc_id = doc_id if isinstance(doc_id, str) else doc_id.group(1)
                        parts.append(
                            f"Here is the information for document ID **{doc_id or 'unknown'}**:\n"
                            + "\n".join(f"- **{k}**: {v}" for k, v in data.items())
                        )
                    else:
                        doc_match2 = _DOC_PAT.search(text)
                        doc_id2 = doc_match2.group(1) if doc_match2 else "unknown"
                        parts.append(f"No transaction found for document ID **{doc_id2}**.")
                except Exception:
                    parts.append(tm.content or "No data returned.")
            return AIMessage(content="\n\n".join(parts))

        # First call — decide which tool to invoke
        lower = text.lower()
        doc_match = _DOC_PAT.search(text)
        doc_id = doc_match.group(1) if doc_match else "UNKNOWN"

        if any(w in lower for w in ["tenant", "processed by"]):
            tool_name = "get_tenant_id"
        else:
            tool_name = "get_transaction_details"

        msg = AIMessage(content="")
        msg.tool_calls = [{"name": tool_name, "args": {"document_id": doc_id}, "id": "mock_call_1"}]
        return msg

    mock = MagicMock()
    mock.bind_tools.return_value = mock
    mock.ainvoke = AsyncMock(side_effect=_ainvoke)
    return mock

# Regex to extract a document ID from a user query (e.g. TXN-001, DOC-42, INV-2024-001)
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
    return "sap/anthropic--claude-4.5-sonnet"


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
        import os
        if os.environ.get("IBD_TESTING") == "1":
            self.llm = _build_mock_llm()
        else:
            from langchain_litellm import ChatLiteLLM
            self.llm = ChatLiteLLM(model=get_model_name(), temperature=get_temperature())
        self._graph = None

    def _build_graph(self, tools):
        llm_with_tools = self.llm.bind_tools(tools)
        tool_node = ToolNode(tools)

        def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
            last = state["messages"][-1]
            if hasattr(last, "tool_calls") and last.tool_calls:
                return "tools"
            return "__end__"

        async def call_model(state: MessagesState):
            response = await llm_with_tools.ainvoke(state["messages"])
            return {"messages": [response]}

        builder = StateGraph(MessagesState)
        builder.add_node("model", call_model)
        builder.add_node("tools", tool_node)
        builder.add_edge(START, "model")
        builder.add_conditional_edges("model", should_continue, {"tools": "tools", "__end__": END})
        builder.add_edge("tools", "model")
        return builder.compile()

    async def _get_graph(self):
        if self._graph is None:
            tools = await get_mcp_tools()
            logger.info("Building graph with %d tool(s): %s", len(tools), [t.name for t in tools])
            self._graph = self._build_graph(tools)
        return self._graph

    # ------------------------------------------------------------------
    # Milestone helpers
    # ------------------------------------------------------------------

    @tracer.start_as_current_span("m1_user_query_received")
    def _m1_user_query_received(self, query: str) -> Optional[str]:
        document_id = _extract_document_id(query)
        if document_id:
            logger.info("M1.achieved: user query received with document_id=%s", document_id)
        else:
            logger.warning("M1.missed: no document_id detected in user query")
        return document_id

    @tracer.start_as_current_span("m2_tool_selected")
    def _m2_tool_selected(self, result: dict, document_id: Optional[str]) -> Optional[str]:
        messages = result.get("messages", [])
        for msg in reversed(messages):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                tool_name = msg.tool_calls[0].get("name") if isinstance(msg.tool_calls[0], dict) else msg.tool_calls[0].name
                logger.info("M2.achieved: tool selected=%s for document_id=%s", tool_name, document_id)
                return tool_name
        logger.warning("M2.missed: could not determine tool for query, document_id=%s", document_id)
        return None

    @tracer.start_as_current_span("m3_data_retrieved")
    def _m3_data_retrieved(self, result: dict, document_id: Optional[str], tool_name: Optional[str]):
        messages = result.get("messages", [])
        for msg in messages:
            if hasattr(msg, "type") and msg.type == "tool" and msg.content:
                logger.info(
                    "M3.achieved: data retrieved for document_id=%s, tool=%s",
                    document_id,
                    tool_name,
                )
                return
        logger.warning(
            "M3.missed: tool returned no data or error for document_id=%s, tool=%s",
            document_id,
            tool_name,
        )

    @tracer.start_as_current_span("m4_response_formatted")
    def _m4_response_formatted(self, response: str, document_id: Optional[str]):
        if response:
            logger.info("M4.achieved: response formatted for document_id=%s", document_id)
        else:
            logger.warning("M4.missed: response formatting failed for document_id=%s", document_id)

    @tracer.start_as_current_span("m5_document_id_confirmed")
    def _m5_document_id_confirmed(self, response: str, document_id: Optional[str]):
        if document_id and document_id.lower() in response.lower():
            logger.info(
                "M5.achieved: document_id echoed in response, document_id=%s", document_id
            )
        else:
            logger.warning(
                "M5.missed: document_id not present in agent response, document_id=%s",
                document_id,
            )

    # ------------------------------------------------------------------
    # Core execution methods
    # ------------------------------------------------------------------

    async def stream(self, query: str, context_id: str) -> AsyncGenerator[dict, None]:
        yield {
            "is_task_complete": False,
            "require_user_input": False,
            "content": "Processing...",
        }
        try:
            document_id = self._m1_user_query_received(query)

            messages = [
                SystemMessage(content=get_system_prompt()),
                HumanMessage(content=query),
            ]
            result = await (await self._get_graph()).ainvoke({"messages": messages})

            tool_name = self._m2_tool_selected(result, document_id)
            self._m3_data_retrieved(result, document_id, tool_name)

            response = result["messages"][-1].content

            self._m4_response_formatted(response, document_id)
            self._m5_document_id_confirmed(response, document_id)

            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": response,
            }
        except Exception as e:
            logger.error("Agent stream error: %s", e, exc_info=True)
            yield {
                "is_task_complete": True,
                "require_user_input": False,
                "content": f"Error: {e}",
            }

    async def invoke(self, query: str, context_id: str) -> AgentResponse:
        try:
            document_id = self._m1_user_query_received(query)

            messages = [
                SystemMessage(content=get_system_prompt()),
                HumanMessage(content=query),
            ]
            result = await (await self._get_graph()).ainvoke({"messages": messages})

            tool_name = self._m2_tool_selected(result, document_id)
            self._m3_data_retrieved(result, document_id, tool_name)

            response = result["messages"][-1].content

            self._m4_response_formatted(response, document_id)
            self._m5_document_id_confirmed(response, document_id)

            return AgentResponse(status="completed", message=response)
        except Exception as e:
            logger.error("Agent invoke error: %s", e, exc_info=True)
            return AgentResponse(status="error", message=f"Error: {e}")
