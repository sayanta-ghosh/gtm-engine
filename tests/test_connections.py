# -*- coding: utf-8 -*-
"""
ConnectionsManager Unit Tests
==============================

Tests for the tenant connection management system including:
- Local connection lifecycle (initiate, complete, disconnect)
- Tenant data isolation
- Usage tracking
- Connection sync logic
- Composio SDK integration (mocked)
"""

import json
import shutil
import tempfile
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from vault.connections import ConnectionsManager, INTEGRATION_CATALOG


class TestConnectionsLocal:
    """Tests for local (no Composio key) connection management."""

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="conn_test_"))
        self.mgr = ConnectionsManager(base_path=self.tmp, composio_api_key=None)

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_catalog_loaded(self):
        """Integration catalog has expected apps."""
        apps = self.mgr.get_available_apps()
        assert apps["success"]
        assert apps["total"] == len(INTEGRATION_CATALOG)
        assert "slack" in apps["apps"]
        assert "hubspot" in apps["apps"]

    def test_catalog_filter_by_category(self):
        """Can filter catalog by category."""
        crm_apps = self.mgr.get_available_apps(category="crm")
        assert crm_apps["success"]
        for app_id, info in crm_apps["apps"].items():
            assert info["category"] == "crm"

    def test_initiate_connection_no_composio(self):
        """Without Composio key, initiate returns manual flow."""
        result = self.mgr.initiate_connection("tenant-1", "slack")
        assert result["success"]
        assert result["method"] == "manual"
        assert "composio_setup" in result

    def test_initiate_unknown_app(self):
        """Unknown app returns error."""
        result = self.mgr.initiate_connection("tenant-1", "nonexistent")
        assert not result["success"]
        assert "Unknown app" in result["error"]

    def test_complete_connection_api_key(self):
        """Complete connection with API key."""
        self.mgr.initiate_connection("tenant-1", "slack")
        result = self.mgr.complete_connection(
            "tenant-1", "slack", api_key="xoxb-test-key-123"
        )
        assert result["success"]
        assert result["status"] == "active"
        assert result["fingerprint"]  # SHA-256 prefix

    def test_get_tenant_connections(self):
        """Get connections returns all catalog apps with status."""
        # Connect slack
        self.mgr.complete_connection("tenant-1", "slack", api_key="test-key")

        conns = self.mgr.get_tenant_connections("tenant-1")
        assert conns["success"]
        assert conns["summary"]["active"] == 1
        assert conns["summary"]["available"] == len(INTEGRATION_CATALOG) - 1

        # Find slack in connections list
        slack = next(c for c in conns["connections"] if c["app_id"] == "slack")
        assert slack["status"] == "active"
        assert slack["method"] == "api_key"

    def test_disconnect(self):
        """Disconnect removes local connection."""
        self.mgr.complete_connection("tenant-1", "slack", api_key="test-key")
        result = self.mgr.disconnect("tenant-1", "slack")
        assert result["success"]

        # Verify disconnected
        conns = self.mgr.get_tenant_connections("tenant-1")
        slack = next(c for c in conns["connections"] if c["app_id"] == "slack")
        assert slack["status"] == "not_connected"

    def test_disconnect_not_connected(self):
        """Disconnect unknown app returns error."""
        result = self.mgr.disconnect("tenant-1", "slack")
        assert not result["success"]

    def test_usage_tracking(self):
        """Track usage increments counters."""
        self.mgr.complete_connection("tenant-1", "slack", api_key="test-key")

        self.mgr.track_usage("tenant-1", "slack", success=True)
        self.mgr.track_usage("tenant-1", "slack", success=True)
        self.mgr.track_usage("tenant-1", "slack", success=False)

        usage = self.mgr.get_tenant_usage("tenant-1")
        assert usage["success"]
        assert usage["total_calls"] == 3
        assert usage["total_errors"] == 1
        assert usage["breakdown"]["slack"]["total_calls"] == 3
        assert usage["breakdown"]["slack"]["errors"] == 1

    def test_tenant_isolation(self):
        """Tenant A cannot see tenant B's connections."""
        self.mgr.complete_connection("tenant-a", "slack", api_key="key-a")
        self.mgr.complete_connection("tenant-b", "hubspot", api_key="key-b")

        a_conns = self.mgr.get_tenant_connections("tenant-a")
        b_conns = self.mgr.get_tenant_connections("tenant-b")

        a_slack = next(c for c in a_conns["connections"] if c["app_id"] == "slack")
        a_hubspot = next(c for c in a_conns["connections"] if c["app_id"] == "hubspot")
        b_slack = next(c for c in b_conns["connections"] if c["app_id"] == "slack")
        b_hubspot = next(c for c in b_conns["connections"] if c["app_id"] == "hubspot")

        assert a_slack["status"] == "active"
        assert a_hubspot["status"] == "not_connected"
        assert b_slack["status"] == "not_connected"
        assert b_hubspot["status"] == "active"

    def test_admin_overview(self):
        """Admin overview aggregates across tenants."""
        self.mgr.complete_connection("t1", "slack", api_key="k1")
        self.mgr.complete_connection("t2", "slack", api_key="k2")
        self.mgr.complete_connection("t2", "hubspot", api_key="k3")
        self.mgr.track_usage("t1", "slack", success=True)
        self.mgr.track_usage("t2", "slack", success=True)

        overview = self.mgr.admin_overview()
        assert overview["success"]
        assert overview["total_active_connections"] == 3
        assert overview["total_calls"] == 2

    def test_persistence_across_instances(self):
        """Data persists across ConnectionsManager instances."""
        self.mgr.complete_connection("t1", "slack", api_key="test")
        self.mgr.track_usage("t1", "slack", success=True)

        # Create new instance pointing to same path
        mgr2 = ConnectionsManager(base_path=self.tmp, composio_api_key=None)
        conns = mgr2.get_tenant_connections("t1")
        slack = next(c for c in conns["connections"] if c["app_id"] == "slack")
        assert slack["status"] == "active"

    def test_entity_id_generation(self):
        """Entity IDs follow gtm-{tenant_id} pattern."""
        data = self.mgr._get_tenant_data("my-tenant")
        assert data["entity_id"] == "gtm-my-tenant"

    def test_no_credential_leakage(self):
        """API keys should NOT appear in connections.json."""
        self.mgr.complete_connection("t1", "slack", api_key="super-secret-key-123")

        raw = self.mgr.connections_file.read_text()
        assert "super-secret-key-123" not in raw
        # Only fingerprint should be stored
        assert raw.count("credential_fingerprint") >= 1


class TestConnectionsComposio:
    """Tests for Composio SDK integration (mocked)."""

    def setup_method(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="conn_composio_"))
        self.mgr = ConnectionsManager(
            base_path=self.tmp, composio_api_key="test-composio-key"
        )

    def teardown_method(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("vault.connections.ConnectionsManager._get_composio_client")
    def test_initiate_oauth(self, mock_client_fn):
        """Initiating OAuth calls Composio SDK."""
        # Mock the SDK response chain
        mock_client = MagicMock()
        mock_entity = MagicMock()
        mock_conn_request = MagicMock()
        mock_conn_request.redirectUrl = "https://accounts.google.com/o/oauth2/auth?..."
        mock_conn_request.connectedAccountId = "acc-12345"
        mock_conn_request.connectionStatus = "INITIATED"

        mock_client.get_entity.return_value = mock_entity
        mock_entity.initiate_connection.return_value = mock_conn_request
        mock_client_fn.return_value = mock_client

        result = self.mgr.initiate_connection("tenant-1", "slack")

        assert result["success"]
        assert result["oauth_url"] == "https://accounts.google.com/o/oauth2/auth?..."
        assert result["connected_account_id"] == "acc-12345"

        # Verify SDK was called correctly
        mock_client.get_entity.assert_called_once_with(id="gtm-tenant-1")
        mock_entity.initiate_connection.assert_called_once()
        call_kwargs = mock_entity.initiate_connection.call_args
        assert call_kwargs.kwargs["app_name"] == "SLACK"

    @patch("vault.connections.ConnectionsManager._get_composio_client")
    def test_sync_picks_up_new_connections(self, mock_client_fn):
        """Sync updates local state from Composio."""
        mock_client = MagicMock()
        mock_entity = MagicMock()

        # Simulate Composio having an active Slack connection
        mock_conn = MagicMock()
        mock_conn.appUniqueId = "slack"
        mock_conn.appName = "Slack"
        mock_conn.id = "composio-conn-id-abc"
        mock_conn.status = "ACTIVE"
        mock_conn.createdAt = "2024-01-15T10:00:00Z"

        mock_entity.get_connections.return_value = [mock_conn]
        mock_client.get_entity.return_value = mock_entity
        mock_client_fn.return_value = mock_client

        result = self.mgr.sync_connection_status("tenant-1")

        assert result["success"]
        assert "slack" in result["synced"]

        # Verify local state was updated
        conns = self.mgr.get_tenant_connections("tenant-1")
        slack = next(c for c in conns["connections"] if c["app_id"] == "slack")
        assert slack["status"] == "active"

    @patch("vault.connections.ConnectionsManager._get_composio_client")
    def test_sync_marks_stale_oauth_disconnected(self, mock_client_fn):
        """Sync marks locally-active OAuth connections as disconnected if missing from Composio."""
        mock_client = MagicMock()
        mock_entity = MagicMock()
        mock_entity.get_connections.return_value = []  # No connections in Composio
        mock_client.get_entity.return_value = mock_entity
        mock_client_fn.return_value = mock_client

        # Manually set a local OAuth connection as active
        tenant_data = self.mgr._get_tenant_data("tenant-1")
        tenant_data["connections"]["slack"] = {
            "status": "active",
            "method": "oauth",
            "app_name": "Slack",
            "category": "communication",
        }
        self.mgr._save()

        result = self.mgr.sync_connection_status("tenant-1")
        assert "slack" in result["synced"]

        conns = self.mgr.get_tenant_connections("tenant-1")
        slack = next(c for c in conns["connections"] if c["app_id"] == "slack")
        assert slack["status"] == "disconnected"

    @patch("vault.connections.ConnectionsManager._get_composio_client")
    def test_disconnect_revokes_composio(self, mock_client_fn):
        """Disconnect calls Composio to revoke the connection."""
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        # Set up a local connection with composio ID
        tenant_data = self.mgr._get_tenant_data("tenant-1")
        tenant_data["connections"]["slack"] = {
            "status": "active",
            "method": "oauth",
            "app_name": "Slack",
            "category": "communication",
            "composio_connection_id": "composio-abc-123",
        }
        self.mgr._save()

        result = self.mgr.disconnect("tenant-1", "slack")
        assert result["success"]

        # Verify Composio revocation was called
        mock_client.http.delete.assert_called_once_with(
            url="/v1/connectedAccounts/composio-abc-123"
        )

    @patch("vault.connections.ConnectionsManager._get_composio_client")
    def test_disconnect_handles_composio_failure(self, mock_client_fn):
        """Disconnect succeeds even if Composio revocation fails."""
        mock_client = MagicMock()
        mock_client.http.delete.side_effect = Exception("Composio API error")
        mock_client_fn.return_value = mock_client

        tenant_data = self.mgr._get_tenant_data("tenant-1")
        tenant_data["connections"]["slack"] = {
            "status": "active",
            "method": "oauth",
            "composio_connection_id": "bad-id",
            "app_name": "Slack",
            "category": "communication",
        }
        self.mgr._save()

        # Should still succeed locally even if Composio fails
        result = self.mgr.disconnect("tenant-1", "slack")
        assert result["success"]

    @patch("vault.connections.ConnectionsManager._get_composio_client")
    def test_resolve_app_from_connection(self, mock_client_fn):
        """Can resolve app_id from a Composio connected_account_id."""
        mock_client = MagicMock()
        mock_account = MagicMock()
        mock_account.appUniqueId = "slack"
        mock_client.connected_accounts.get.return_value = mock_account
        mock_client_fn.return_value = mock_client

        app_id = self.mgr.resolve_app_from_connection("conn-abc-123")
        assert app_id == "slack"

    def test_sync_no_api_key(self):
        """Sync without API key returns gracefully."""
        mgr = ConnectionsManager(base_path=self.tmp, composio_api_key=None)
        result = mgr.sync_connection_status("tenant-1")
        assert not result["success"]
        assert result["reason"] == "no_api_key"

    def test_mcp_url_no_key_exposure(self):
        """MCP URL helper does NOT expose API key."""
        result = self.mgr.get_composio_mcp_url("tenant-1")
        assert result["success"]
        assert "test-composio-key" not in json.dumps(result)
        assert "YOUR_KEY" in result["setup_command"]
        assert "gtm-tenant-1" in result["setup_command"]


def run_all_tests():
    """Run all tests and report results."""
    import traceback

    test_classes = [TestConnectionsLocal, TestConnectionsComposio]
    passed = 0
    failed = 0
    errors = []

    for cls in test_classes:
        print(f"\n{'=' * 60}")
        print(f"  {cls.__name__}")
        print(f"{'=' * 60}")

        for method_name in sorted(dir(cls)):
            if not method_name.startswith("test_"):
                continue

            instance = cls()
            instance.setup_method()

            try:
                getattr(instance, method_name)()
                print(f"  ✅ {method_name}")
                passed += 1
            except Exception as e:
                print(f"  ❌ {method_name}: {e}")
                errors.append((cls.__name__, method_name, traceback.format_exc()))
                failed += 1
            finally:
                instance.teardown_method()

    print(f"\n{'=' * 60}")
    print(f"  RESULTS: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")

    if errors:
        print("\n--- FAILURES ---")
        for cls_name, method, tb in errors:
            print(f"\n{cls_name}.{method}:")
            print(tb)

    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
