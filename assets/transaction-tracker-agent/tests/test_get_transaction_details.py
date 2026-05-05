"""Unit tests for the get_transaction_details tool."""
import pytest


@pytest.fixture(autouse=True)
def _path(add_agent_to_path):
    """Ensure app/ is on sys.path via the shared fixture."""


class MockDBClient:
    """Minimal stub that returns predictable data without a real DB."""

    TRANSACTIONS = {
        "TXN-001": {
            "document_id": "TXN-001",
            "status": "Completed",
            "amount": "1000.00",
            "currency": "USD",
            "created_at": "2026-01-15T10:00:00Z",
            "updated_at": "2026-01-15T10:05:00Z",
            "type": "PAYMENT",
            "reference": "REF-2026-001",
        }
    }

    def get_transaction_details(self, document_id: str):
        return self.TRANSACTIONS.get(document_id)

    def get_tenant_id(self, document_id: str):
        return None


def test_get_transaction_details_valid(add_agent_to_path):
    """Valid document ID returns expected transaction fields."""
    import tools.database as db_module
    from tools.get_transaction_details import _get_transaction_details

    original = db_module._db_client
    try:
        db_module._db_client = MockDBClient()
        result = _get_transaction_details("TXN-001")
        assert result["document_id"] == "TXN-001"
        assert result["status"] == "Completed"
        assert result["amount"] == "1000.00"
        assert result["currency"] == "USD"
    finally:
        db_module._db_client = original


def test_get_transaction_details_not_found(add_agent_to_path):
    """Non-existent document ID returns an empty dict."""
    import tools.database as db_module
    from tools.get_transaction_details import _get_transaction_details

    original = db_module._db_client
    try:
        db_module._db_client = MockDBClient()
        result = _get_transaction_details("TXN-999")
        assert result == {}
    finally:
        db_module._db_client = original


def test_get_transaction_details_tool_name(add_agent_to_path):
    """Tool has correct name and description."""
    from tools.get_transaction_details import get_transaction_details_tool

    assert get_transaction_details_tool.name == "get_transaction_details"
    assert "Transaction Tracker" in get_transaction_details_tool.description


def test_get_transaction_details_tool_schema(add_agent_to_path):
    """Tool args schema requires document_id."""
    from tools.get_transaction_details import get_transaction_details_tool

    schema = get_transaction_details_tool.args_schema.model_json_schema()
    assert "document_id" in schema["properties"]
    assert "document_id" in schema.get("required", [])
