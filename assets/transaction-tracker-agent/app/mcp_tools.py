"""MCP tool loader.

Owned indirection layer between agent code and the Agent Gateway.
All agent code imports get_mcp_tools from here.

Behaviour is controlled by the IBD_TESTING environment variable:

  Production (IBD_TESTING not set):
      Uses MCPClient (mcp_client.py) to connect to the Agent Gateway via mTLS.
      Credentials are loaded from the UMS volume mount (/etc/ums/credentials/credentials)
      or the AGW_CREDENTIALS_JSON environment variable.

  Local / test mode (IBD_TESTING=1):
      Reads mcp-mock.json from the directory containing this file's parent
      (i.e. <asset-root>/mcp-mock.json) and returns LangChain StructuredTool
      instances built from the mock data â no network calls.
"""

import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# mcp-mock.json lives at the asset root (one level above app/)
_MOCK_FILE = Path(__file__).parent.parent / "mcp-mock.json"


def _build_mock_tools() -> list:
    """Build LangChain StructuredTool instances from mcp-mock.json.

    Returns an empty list (without error) when mcp-mock.json is absent or
    cannot be parsed â add/fix the file to enable tool mocking.
    """
    if not _MOCK_FILE.exists():
        return []

    try:
        mock_data = json.loads(_MOCK_FILE.read_text())
    except Exception:
        logger.warning("Failed to parse mcp-mock.json at %s â returning empty tool list", _MOCK_FILE, exc_info=True)
        return []

    tools = []

    from langchain_core.tools import StructuredTool
    from pydantic import Field, create_model

    for _server_slug, server in mock_data.get("servers", {}).items():
        for tool_name, tool_def in server.get("tools", {}).items():
            description = tool_def.get("description", "")
            mock_response = tool_def.get("mock_response", {})
            input_schema = tool_def.get("input_schema", {})

            props = input_schema.get("properties", {})
            required_fields = set(input_schema.get("required", []))
            field_definitions: dict = {}
            for field_name, field_info in props.items():
                json_type = field_info.get("type", "string")
                if json_type == "integer":
                    python_type = int
                elif json_type == "number":
                    python_type = float
                elif json_type == "boolean":
                    python_type = bool
                else:
                    python_type = str

                if field_name in required_fields:
                    field_definitions[field_name] = (python_type, Field(description=field_info.get("description", "")))
                else:
                    field_definitions[field_name] = (python_type, Field(default=None, description=field_info.get("description", "")))

            args_schema = create_model(f"{tool_name}_args", **field_definitions) if field_definitions else create_model(f"{tool_name}_args")

            # Create a smart mock function that adapts response based on document_id
            def _make_mock_function(_tool_name, _mock_response):
                async def _coroutine(**kwargs) -> str:
                    document_id = kwargs.get("document_id", "")

                    # For search_transactions: adapt the response to match the requested document_id
                    if _tool_name == "search_transactions" and document_id:
                        # Check for known test document IDs
                        if document_id == "TXN-999" or document_id.endswith("-999"):
                            # Return empty dict for "not found" scenario
                            return json.dumps({})

                        # Use the main mock response and adapt it
                        response = _mock_response.copy()

                        # Update documentId to match the request
                        response["documentId"] = document_id

                        # Vary status based on document ID for testing different scenarios
                        if "abc" in document_id.lower():
                            response["status"] = "S"  # Success
                            response["id"] = "AGnABC123xyz456789"
                        elif "err" in document_id.lower():
                            response["status"] = "F"  # Failed
                            response["id"] = "AGnERR123xyz456789"
                        elif "proc" in document_id.lower():
                            response["status"] = "P"  # Processing
                            response["id"] = "AGnPROC123xyz456789"
                        else:
                            # Keep "R" (Received) as default
                            pass

                        return json.dumps(response)

                    # For get_transaction_details: return comprehensive detail
                    elif _tool_name == "get_transaction_details" and document_id:
                        if document_id == "TXN-999" or document_id.endswith("-999"):
                            # Return empty dict for "not found" scenario
                            return json.dumps({})

                        # Use the main mock response and adapt the documentId
                        response = _mock_response.copy()
                        if "information" in response:
                            response["information"]["documentId"] = document_id

                        return json.dumps(response)

                    # For get_tenant_id: handle known scenarios
                    elif _tool_name == "get_tenant_id" and document_id:
                        if document_id == "TXN-999" or document_id.endswith("-999"):
                            # Return empty dict for "not found" scenario
                            return json.dumps({})

                        # Return tenant based on document ID pattern
                        response = _mock_response.copy()
                        return json.dumps(response)

                    # Default: return original mock response
                    return json.dumps(_mock_response)

                return _coroutine

            tools.append(
                StructuredTool(
                    name=tool_name,
                    description=description,
                    args_schema=args_schema,
                    coroutine=_make_mock_function(tool_name, mock_response),
                )
            )

    logger.info("Loaded %d mock MCP tool(s) from %s", len(tools), _MOCK_FILE)
    return tools


async def get_mcp_tools() -> list:
    """Return LangChain-compatible tools for the Transaction Tracker Agent.

    In local/test mode (IBD_TESTING=1): returns mock tools from mcp-mock.json.
    In production: returns the custom Transaction Tracker tools directly.
    """
    if os.environ.get("IBD_TESTING") == "1":
        return _build_mock_tools()

    # Custom tools — backed by the injectable TransactionTrackerClient
    from tools import search_transactions_tool, get_transaction_details_tool, get_tenant_id_tool
    tools = [search_transactions_tool, get_transaction_details_tool, get_tenant_id_tool]
    logger.info("Loaded %d Transaction Tracker tool(s)", len(tools))
    return tools
