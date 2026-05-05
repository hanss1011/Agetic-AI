"""Unit tests for the get_tenant_id tool."""
import pytest


@pytest.fixture(autouse=True)
def _path(add_agent_to_path):
    """Ensure app/ is on sys.path via the shared fixture."""


class MockDBClient:
    """Minimal stub that returns predictable data without a real DB."""

    TENANTS = {
        "TXN-001": {"tenant_id": "TENANT-A"},
        "TXN-042": {"tenant_id": "TENANT-B"},
    }

    def get_transaction_details(self, document_id: str):
        return None

    def get_tenant_id(self, document_id: str):
        return self.TENANTS.get(document_id)


def test_get_tenant_id_valid(add_agent_to_path):
    """Valid document ID returns the expected tenant_id."""
    import tools.database as db_module
    from tools.get_tenant_id import _get_tenant_id

    original = db_module._db_client
    try:
        db_module._db_client = MockDBClient()
        result = _get_tenant_id("TXN-001")
        assert result == {"tenant_id": "TENANT-A"}
    finally:
        db_module._db_client = original


def test_get_tenant_id_second_tenant(add_agent_to_path):
    """Another valid document ID returns its tenant_id."""
    import tools.database as db_module
    from tools.get_tenant_id import _get_tenant_id

    original = db_module._db_client
    try:
        db_module._db_client = MockDBClient()
        result = _get_tenant_id("TXN-042")
        assert result["tenant_id"] == "TENANT-B"
    finally:
        db_module._db_client = original


def test_get_tenant_id_not_found(add_agent_to_path):
    """Non-existent document ID returns an empty dict."""
    import tools.database as db_module
    from tools.get_tenant_id import _get_tenant_id

    original = db_module._db_client
    try:
        db_module._db_client = MockDBClient()
        result = _get_tenant_id("TXN-999")
        assert result == {}
    finally:
        db_module._db_client = original


def test_get_tenant_id_tool_name(add_agent_to_path):
    """Tool has correct name and description."""
    from tools.get_tenant_id import get_tenant_id_tool

    assert get_tenant_id_tool.name == "get_tenant_id"
    assert "tenant" in get_tenant_id_tool.description.lower()


def test_get_tenant_id_tool_schema(add_agent_to_path):
    """Tool args schema requires document_id."""
    from tools.get_tenant_id import get_tenant_id_tool

    schema = get_tenant_id_tool.args_schema.model_json_schema()
    assert "document_id" in schema["properties"]
    assert "document_id" in schema.get("required", [])
