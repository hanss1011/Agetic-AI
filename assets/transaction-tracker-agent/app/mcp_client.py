"""
MCP Client for Agent Gateway Integration.

Loads MCP tools from Agent Gateway using volume mount or environment variable credentials with mTLS authentication.
"""

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from typing import Any, Callable

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

logger = logging.getLogger(__name__)

# Hardcoded MCP endpoint path (will be configurable in the future)
MCP_ENDPOINT_PATH = "/v1/mcp/sap.mcpbuilder:apiResource:cost-center:v1/730297600"

# Resource name for token request
AGW_RESOURCE_NAME = "agent-gateway"


@dataclass
class AgwCredentials:
    """Credentials for Agent Gateway authentication."""
    
    auth_type: str
    certificate: str
    client_id: str
    expires_at: str
    gateway_url: str
    private_key: str
    token_service_url: str
    uri: str
    
    @classmethod
    def from_dict(cls, data: dict) -> "AgwCredentials":
        """Create credentials from dictionary."""
        return cls(
            auth_type=data.get("authType", ""),
            certificate=data.get("certificate", ""),
            client_id=data.get("clientid", ""),
            expires_at=data.get("expiresAt", ""),
            gateway_url=data.get("gatewayUrl", ""),
            private_key=data.get("privateKey", ""),
            token_service_url=data.get("tokenServiceUrl", ""),
            uri=data.get("uri", ""),
        )
    
    @property
    def mcp_url(self) -> str:
        """Get the full MCP server URL."""
        return f"{self.gateway_url.rstrip('/')}{MCP_ENDPOINT_PATH}"


@dataclass
class MCPTool:
    """Represents an MCP tool."""
    
    name: str
    server_name: str
    description: str
    input_schema: dict
    url: str
    
    @property
    def namespaced_name(self) -> str:
        """Get namespaced tool name."""
        return f"{self.server_name}__{self.name}"


# Path where UMS operator mounts credentials
UMS_CREDENTIALS_PATH = "/etc/ums/credentials/credentials"


def load_agw_credentials() -> AgwCredentials | None:
    """
    Load Agent Gateway credentials from volume mount or environment variable.
    
    Tries in order:
        1. Volume mount at /etc/ums/credentials/credentials (UMS operator)
        2. AGW_CREDENTIALS_JSON environment variable (fallback)
        
    Returns:
        AgwCredentials if credentials are present and valid, None otherwise
    """
    data = None
    source = None
    
    # Try volume mount first (UMS operator)
    if os.path.exists(UMS_CREDENTIALS_PATH):
        try:
            with open(UMS_CREDENTIALS_PATH, "r") as f:
                data = json.load(f)
            source = f"volume mount ({UMS_CREDENTIALS_PATH})"
            logger.info(f"Found credentials at {UMS_CREDENTIALS_PATH}")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse credentials from {UMS_CREDENTIALS_PATH}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to read credentials from {UMS_CREDENTIALS_PATH}: {e}")
            return None
    
    # Fallback to environment variable
    if data is None:
        credentials_json = os.environ.get("AGW_CREDENTIALS_JSON", "")
        if credentials_json:
            try:
                data = json.loads(credentials_json)
                source = "AGW_CREDENTIALS_JSON environment variable"
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse AGW_CREDENTIALS_JSON: {e}")
                return None
    
    if data is None:
        logger.info("No AGW credentials found (neither volume mount nor environment variable) - MCP tools will not be available")
        return None
    
    try:
        credentials = AgwCredentials.from_dict(data)
        
        # Validate required fields
        if not credentials.gateway_url:
            logger.warning("AGW credentials missing required field (gatewayUrl)")
            return None
        
        if not credentials.client_id:
            logger.warning("AGW credentials missing required field (clientid)")
            return None
        
        if not credentials.certificate or not credentials.private_key or not credentials.token_service_url:
            logger.warning("AGW mTLS credentials incomplete (certificate, privateKey, tokenServiceUrl)")
            return None
        
        logger.info(f"Loaded AGW credentials from {source} for client_id: {credentials.client_id[:8]}...")
        return credentials
        
    except Exception as e:
        logger.error(f"Failed to load AGW credentials: {e}")
        return None


async def get_oauth_token(credentials: AgwCredentials) -> str:
    """
    Get OAuth token using mTLS authentication.
    
    Args:
        credentials: AGW credentials with certificate and private key
        
    Returns:
        Bearer token string
        
    Raises:
        Exception if token retrieval fails
    """
    # Write certificate and key to temporary files for mTLS
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as cert_file:
        cert_file.write(credentials.certificate)
        cert_path = cert_file.name
    
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as key_file:
        key_file.write(credentials.private_key)
        key_path = key_file.name
    
    try:
        # Create SSL context with client certificate
        async with httpx.AsyncClient(
            cert=(cert_path, key_path),
            timeout=30.0,
        ) as client:
            response = await client.post(
                credentials.token_service_url,
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={
                    "client_id": credentials.client_id,
                    "grant_type": "client_credentials",
                    "resource": f"urn:sap:identity:application:provider:name:{AGW_RESOURCE_NAME}",
                },
            )
            response.raise_for_status()
            token_data = response.json()
            access_token = token_data.get("access_token")
            if not access_token:
                raise ValueError("No access_token in response")
            logger.info("Successfully obtained OAuth token from IAS")
            return f"Bearer {access_token}"
    finally:
        # Clean up temporary files
        try:
            os.unlink(cert_path)
            os.unlink(key_path)
        except Exception:
            pass


class MCPClient:
    """
    Client for discovering and calling MCP tools via Agent Gateway.
    
    Uses volume mount credentials with mTLS authentication.
    """
    
    def __init__(self, credentials: AgwCredentials | None = None):
        """
        Initialize MCP client.
        
        Args:
            credentials: AGW credentials, or None to load from default path
        """
        self.credentials = credentials or load_agw_credentials()
        self._cached_token: str | None = None
    
    async def _get_auth_header(self) -> str:
        """Get authorization header, fetching a fresh token each time."""
        if not self.credentials:
            raise ValueError("No AGW credentials available")
        
        # Always fetch a fresh token (no caching for now)
        logger.debug("Fetching fresh OAuth token...")
        token = await get_oauth_token(self.credentials)
        logger.debug("OAuth token obtained successfully")
        return token
    
    async def get_mcp_tools(self) -> list[MCPTool]:
        """
        Discover available MCP tools from Agent Gateway.
        
        Returns:
            List of MCPTool objects
        """
        if not self.credentials:
            logger.warning("No AGW credentials available - skipping MCP tool discovery")
            return []
        
        tools: list[MCPTool] = []
        mcp_url = self.credentials.mcp_url
        
        try:
            auth_header = await self._get_auth_header()
            
            async with httpx.AsyncClient(
                headers={"Authorization": auth_header},
                timeout=30.0,
            ) as http_client:
                async with streamable_http_client(mcp_url, http_client=http_client) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        init_result = await session.initialize()
                        server_name = (
                            init_result.serverInfo.name
                            if init_result and init_result.serverInfo and init_result.serverInfo.name
                            else "agent-gateway"
                        )
                        
                        result = await session.list_tools()
                        tools = [
                            MCPTool(
                                name=t.name,
                                server_name=server_name,
                                description=t.description or "",
                                input_schema=t.inputSchema or {},
                                url=mcp_url,
                            )
                            for t in result.tools
                        ]
                        
            logger.info(f"Discovered {len(tools)} MCP tool(s) from Agent Gateway")
            return tools
            
        except Exception as e:
            logger.exception(f"Failed to discover MCP tools: {e}")
            return []
    
    async def call_tool(self, tool: MCPTool, **kwargs) -> str:
        """
        Call an MCP tool.
        
        Args:
            tool: The MCPTool to call
            **kwargs: Tool arguments
            
        Returns:
            Tool result as string
        """
        logger.info(f"call_tool START: tool={tool.name}, args={kwargs}")
        
        if not self.credentials:
            logger.error("call_tool: No AGW credentials available")
            raise ValueError("No AGW credentials available")
        
        logger.info("call_tool: Getting auth header...")
        auth_header = await self._get_auth_header()
        logger.info("call_tool: Auth header obtained")
        
        logger.info(f"call_tool: Creating HTTP client for URL: {tool.url}")
        async with httpx.AsyncClient(
            headers={"Authorization": auth_header},
            timeout=60.0,
        ) as http_client:
            logger.info("call_tool: Opening streamable_http_client...")
            async with streamable_http_client(tool.url, http_client=http_client) as (read, write, _):
                logger.info("call_tool: Creating ClientSession...")
                async with ClientSession(read, write) as session:
                    logger.info("call_tool: Calling session.initialize()...")
                    await session.initialize()
                    logger.info(f"call_tool: Initialize complete, calling session.call_tool({tool.name}, {kwargs})...")
                    result = await session.call_tool(tool.name, kwargs)
                    logger.info(f"call_tool: session.call_tool returned, result={result}")
                    response = str(result.content[0].text if result.content else "")
                    logger.info(f"call_tool END: returning response (length={len(response)})")
                    return response


class MCPToolConverter:
    """
    Converter for transforming MCP tools to various framework formats.
    
    Provides methods to convert MCPTool objects to tools compatible with
    different agent frameworks like LangChain.
    """
    
    def __init__(self, mcp_client: MCPClient):
        """
        Initialize the converter.
        
        Args:
            mcp_client: MCP client for tool execution
        """
        self.mcp_client = mcp_client
    
    def to_langchain(self, mcp_tool: MCPTool) -> "StructuredTool":
        """
        Convert an MCP tool to a LangChain StructuredTool.
        
        Args:
            mcp_tool: The MCP tool to convert
            
        Returns:
            LangChain StructuredTool
        """
        from langchain_core.tools import StructuredTool
        from pydantic import create_model
        
        mcp_client = self.mcp_client
        
        async def run(**kwargs) -> str:
            return await mcp_client.call_tool(mcp_tool, **kwargs)
        
        # Build args schema from input_schema
        properties = mcp_tool.input_schema.get("properties", {})
        required = set(mcp_tool.input_schema.get("required", []))
        
        fields = {}
        for name, prop in properties.items():
            # Map JSON schema types to Python types
            prop_type = prop.get("type", "string")
            python_type = str  # Default to string
            if prop_type == "integer":
                python_type = int
            elif prop_type == "number":
                python_type = float
            elif prop_type == "boolean":
                python_type = bool
            
            # Required fields use ... (Ellipsis), optional use None default
            if name in required:
                fields[name] = (python_type, ...)
            else:
                fields[name] = (python_type | None, None)
        
        args_schema = create_model(f"{mcp_tool.name}_args", **fields) if fields else None
        
        return StructuredTool.from_function(
            coroutine=run,
            name=mcp_tool.name,
            description=mcp_tool.description,
            args_schema=args_schema,
        )
