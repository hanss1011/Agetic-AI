"""
Tool: get_tenant_id

Retrieves the tenant identifier associated with a transaction from the
Transaction Tracker API given a document ID.
"""
import asyncio
import logging
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from tools.api_client import get_api_client

logger = logging.getLogger(__name__)


class GetTenantIdInput(BaseModel):
    document_id: str = Field(
        description="The unique document ID of the transaction whose processing tenant is required (e.g. TXN-001)."
    )


async def _get_tenant_id_async(document_id: str) -> dict:
    """
    Query the Transaction Tracker API for the tenant ID associated with
    the transaction identified by *document_id*.

    Returns a dict with a 'tenant_id' key, or an empty dict if the
    document ID is not found.
    """
    try:
        client = get_api_client()
        result: Optional[dict] = await client.get_tenant_id(document_id)
        if result:
            logger.info("Retrieved tenant ID for document_id=%s", document_id)
            return result

        logger.warning("No tenant found for document_id=%s", document_id)
        return {}

    except Exception as exc:
        logger.error(
            "get_tenant_id failed for document_id=%s: %s",
            document_id,
            exc,
            exc_info=True
        )
        return {}


def _get_tenant_id(document_id: str) -> dict:
    """
    Synchronous wrapper for the async tenant ID lookup.

    LangChain tools can be either sync or async. This wrapper allows the tool
    to work in both contexts.
    """
    try:
        # Try to get existing event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're already in an async context, create a task
            return asyncio.create_task(_get_tenant_id_async(document_id))
        else:
            # Run in the existing event loop
            return loop.run_until_complete(_get_tenant_id_async(document_id))
    except RuntimeError:
        # No event loop exists, create a new one
        return asyncio.run(_get_tenant_id_async(document_id))


get_tenant_id_tool = StructuredTool.from_function(
    func=_get_tenant_id,
    name="get_tenant_id",
    description=(
        "Retrieve the tenant identifier from the Transaction Tracker API "
        "for the transaction with the given document ID. Returns a dict with a 'tenant_id' key, "
        "or an empty dict if the document ID does not exist."
    ),
    args_schema=GetTenantIdInput,
    coroutine=_get_tenant_id_async,  # Support async execution
)
