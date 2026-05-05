"""
Tool: get_transaction_details

Retrieves all available fields for a transaction from the Transaction Tracker
API given a document ID.
"""
import asyncio
import logging
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from tools.api_client import get_api_client

logger = logging.getLogger(__name__)


class GetTransactionDetailsInput(BaseModel):
    document_id: str = Field(
        description="The unique document ID of the transaction to look up (e.g. TXN-001)."
    )


async def _get_transaction_details_async(document_id: str) -> dict:
    """
    Query the Transaction Tracker API for all fields of the transaction
    identified by *document_id*.

    Returns a dict containing the transaction fields and their values,
    or an empty dict if the document ID is not found.
    """
    try:
        client = get_api_client()
        result: Optional[dict] = await client.get_transaction_details(document_id)
        if result:
            logger.info("Retrieved transaction details for document_id=%s", document_id)
            return result

        logger.warning("No transaction found for document_id=%s", document_id)
        return {}

    except Exception as exc:
        logger.error(
            "get_transaction_details failed for document_id=%s: %s",
            document_id,
            exc,
            exc_info=True
        )
        return {}


def _get_transaction_details(document_id: str) -> dict:
    """
    Synchronous wrapper for the async transaction details lookup.

    LangChain tools can be either sync or async. This wrapper allows the tool
    to work in both contexts.
    """
    try:
        # Try to get existing event loop
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're already in an async context, create a task
            return asyncio.create_task(_get_transaction_details_async(document_id))
        else:
            # Run in the existing event loop
            return loop.run_until_complete(_get_transaction_details_async(document_id))
    except RuntimeError:
        # No event loop exists, create a new one
        return asyncio.run(_get_transaction_details_async(document_id))


get_transaction_details_tool = StructuredTool.from_function(
    func=_get_transaction_details,
    name="get_transaction_details",
    description=(
        "Retrieve all available transaction fields from the Transaction Tracker API "
        "for a given document ID. Returns a dictionary of field names and values, "
        "or an empty dict if the document ID does not exist."
    ),
    args_schema=GetTransactionDetailsInput,
    coroutine=_get_transaction_details_async,  # Support async execution
)
