"""
Tool: get_tenant_id

Retrieves the tenant identifier associated with a transaction from the
Transaction Tracker database given a document ID.
"""
import logging
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from tools.database import get_db_client

logger = logging.getLogger(__name__)


class GetTenantIdInput(BaseModel):
    document_id: str = Field(
        description="The unique document ID of the transaction whose processing tenant is required (e.g. TXN-001)."
    )


def _get_tenant_id(document_id: str) -> dict:
    """
    Query the Transaction Tracker database for the tenant that processed the
    transaction identified by *document_id*.

    Returns a dict with a ``tenant_id`` key, or an empty dict if the document
    ID is not found.
    """
    try:
        client = get_db_client()
        result: Optional[dict] = client.get_tenant_id(document_id)
        if result:
            return result
        return {}
    except Exception as exc:
        logger.error("get_tenant_id failed for document_id=%s: %s", document_id, exc)
        return {}


get_tenant_id_tool = StructuredTool.from_function(
    func=_get_tenant_id,
    name="get_tenant_id",
    description=(
        "Retrieve the tenant identifier from the Transaction Tracker database "
        "for the transaction with the given document ID. "
        "Returns a dict with a 'tenant_id' key, or an empty dict if the document ID does not exist."
    ),
    args_schema=GetTenantIdInput,
)
