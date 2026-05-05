"""
Injectable data-access layer for the Transaction Tracker database.

In production, this module provides the real database client.
In tests, the caller can replace `get_db_client()` with a mock.
"""
import os
from typing import Optional


class TransactionTrackerClient:
    """Client for the Transaction Tracker database.

    Connection parameters are read from environment variables:
        TRANSACTION_TRACKER_DB_URL  - e.g. postgresql://user:pass@host:5432/txdb
    """

    def __init__(self, db_url: Optional[str] = None):
        self.db_url = db_url or os.environ.get("TRANSACTION_TRACKER_DB_URL", "")

    def get_transaction_details(self, document_id: str) -> Optional[dict]:
        """Return all transaction fields for the given document_id, or None if not found."""
        # Real implementation would execute:
        #   SELECT * FROM transactions WHERE document_id = :document_id
        # For now returns None — wired up via injection in tests.
        raise NotImplementedError(
            "get_transaction_details requires a real database connection. "
            "Set TRANSACTION_TRACKER_DB_URL or inject a test client."
        )

    def get_tenant_id(self, document_id: str) -> Optional[dict]:
        """Return the tenant_id for the given document_id, or None if not found."""
        # Real implementation would execute:
        #   SELECT tenant_id FROM transactions WHERE document_id = :document_id
        raise NotImplementedError(
            "get_tenant_id requires a real database connection. "
            "Set TRANSACTION_TRACKER_DB_URL or inject a test client."
        )


# Module-level client — replaced by tests via monkeypatch
_db_client: Optional[TransactionTrackerClient] = None


def get_db_client() -> TransactionTrackerClient:
    """Return the active database client (lazily initialised)."""
    global _db_client
    if _db_client is None:
        _db_client = TransactionTrackerClient()
    return _db_client


def set_db_client(client: TransactionTrackerClient) -> None:
    """Replace the active client (used in tests)."""
    global _db_client
    _db_client = client
