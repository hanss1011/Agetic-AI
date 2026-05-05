"""
Tool: get_transaction_details

Retrieves all available fields for a transaction from the Transaction Tracker
database given a document ID.
"""
import logging
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from tools.database import get_db_client

logger = logging.getLogger(__name__)


class GetTransactionDetailsInput(BaseModel):
    document_id: str = Field(
        description="The unique document ID of the transaction to look up (e.g. TXN-001)."
    )


def _get_transaction_details(document_id: str) -> dict:
    """
    Query the Transaction Tracker database for all fields of the transaction
    identified by *document_id*.

    Returns a dict containing the transaction fields and their values,
    or an empty dict if the document ID is not found.
    """
    try:
        client = get_db_client()
        result: Optional[dict] = client.get_transaction_details(document_id)
        if result:
            return result
        return {}
    except Exception as exc:
        logger.error("get_transaction_details failed for document_id=%s: %s", document_id, exc)
        return {}


get_transaction_details_tool = StructuredTool.from_function(
    func=_get_transaction_details,
    name="get_transaction_details",
    description=(
        "Retrieve all available transaction fields from the Transaction Tracker database "
        "for a given document ID. Returns a dictionary of field names and values, "
        "or an empty dict if the document ID does not exist."
    ),
    args_schema=GetTransactionDetailsInput,
)
