"""Integration tests: end-to-end agent flow.

The mock MCP tools are loaded from mcp-mock.json (IBD_TESTING=1 is set by conftest.py).
The LLM is mocked to simulate SAP AI Core responses so tests run without external credentials.
In a deployed environment, the real LLM would be used via AI Core.
"""
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage


@pytest.fixture(autouse=True)
def _path(add_agent_to_path):
    """Ensure app/ is on sys.path via the shared fixture."""


def _make_tool_call_message(tool_name: str, document_id: str, tool_call_id: str = "call_1"):
    """Build an AIMessage that requests a tool call."""
    msg = AIMessage(content="")
    msg.tool_calls = [{"name": tool_name, "args": {"document_id": document_id}, "id": tool_call_id}]
    return msg


def _make_final_message(content: str):
    """Build a final AIMessage with the formatted response."""
    return AIMessage(content=content)


@pytest.mark.integration
def test_agent_retrieves_transaction_details(add_agent_to_path):
    """Agent correctly retrieves and formats transaction details for a valid document ID."""
    from agent import SampleAgent

    final_response = (
        "Here are the details for document ID **TXN-001**:\n\n"
        "- **Document ID**: TXN-001\n"
        "- **Status**: Completed\n"
        "- **Amount**: 1000.00 USD\n"
        "- **Type**: PAYMENT\n"
        "- **Created At**: 2026-01-15T10:00:00Z"
    )

    tool_call_msg = _make_tool_call_message("get_transaction_details", "TXN-001")
    tool_result = json.dumps({
        "document_id": "TXN-001", "status": "Completed",
        "amount": "1000.00", "currency": "USD",
        "created_at": "2026-01-15T10:00:00Z", "type": "PAYMENT"
    })
    tool_msg = ToolMessage(content=tool_result, tool_call_id="call_1")
    final_msg = _make_final_message(final_response)

    # Simulate: first LLM call returns tool call, second returns final answer
    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_msg, final_msg])

    agent = SampleAgent()
    with patch.object(agent, "llm", mock_llm):
        agent._graph = None  # reset cached graph so it uses the patched LLM
        result = asyncio.run(agent.invoke("What are the details for document ID TXN-001?", "ctx-1"))

    assert result.status == "completed"
    response = result.message.lower()
    assert "txn-001" in response
    assert any(k in response for k in ["completed", "status", "1000"])


@pytest.mark.integration
def test_agent_returns_not_found_for_missing_document(add_agent_to_path):
    """Agent returns a 'not found' message for a non-existent document ID."""
    from agent import SampleAgent

    final_response = (
        "No transaction was found for document ID **TXN-999**. "
        "Please verify the document ID and try again."
    )

    tool_call_msg = _make_tool_call_message("get_transaction_details", "TXN-999", "call_2")
    tool_msg = ToolMessage(content=json.dumps({}), tool_call_id="call_2")
    final_msg = _make_final_message(final_response)

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_msg, final_msg])

    agent = SampleAgent()
    with patch.object(agent, "llm", mock_llm):
        agent._graph = None
        result = asyncio.run(agent.invoke("Show me transaction details for TXN-999.", "ctx-2"))

    assert result.status == "completed"
    response = result.message.lower()
    assert "txn-999" in response
    assert any(phrase in response for phrase in [
        "not found", "no transaction", "does not exist", "couldn't find",
        "could not find", "unable to find", "no data", "verify"
    ])


@pytest.mark.integration
def test_agent_retrieves_tenant_id(add_agent_to_path):
    """Agent returns the tenant that processed the transaction."""
    from agent import SampleAgent

    final_response = (
        "The transaction with document ID **TXN-001** was processed by tenant **TENANT-A**."
    )

    tool_call_msg = _make_tool_call_message("get_tenant_id", "TXN-001", "call_3")
    tool_msg = ToolMessage(content=json.dumps({"tenant_id": "TENANT-A"}), tool_call_id="call_3")
    final_msg = _make_final_message(final_response)

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_msg, final_msg])

    agent = SampleAgent()
    with patch.object(agent, "llm", mock_llm):
        agent._graph = None
        result = asyncio.run(agent.invoke("Which tenant processed document TXN-001?", "ctx-3"))

    assert result.status == "completed"
    response = result.message.lower()
    assert "txn-001" in response
    assert any(k in response for k in ["tenant", "tenant-a"])


@pytest.mark.integration
def test_agent_always_echoes_document_id(add_agent_to_path):
    """Agent always states the document ID used in every response."""
    from agent import SampleAgent

    final_response = (
        "Here is the information for document ID **TXN-042**:\n\n"
        "- **Tenant ID**: TENANT-B"
    )

    tool_call_msg = _make_tool_call_message("get_tenant_id", "TXN-042", "call_4")
    tool_msg = ToolMessage(content=json.dumps({"tenant_id": "TENANT-B"}), tool_call_id="call_4")
    final_msg = _make_final_message(final_response)

    mock_llm = MagicMock()
    mock_llm.bind_tools.return_value = mock_llm
    mock_llm.ainvoke = AsyncMock(side_effect=[tool_call_msg, final_msg])

    agent = SampleAgent()
    with patch.object(agent, "llm", mock_llm):
        agent._graph = None
        result = asyncio.run(agent.invoke("Give me info on TXN-042.", "ctx-4"))

    assert result.status == "completed"
    assert "txn-042" in result.message.lower()
