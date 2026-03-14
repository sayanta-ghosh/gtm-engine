"""
Tenant Connections Manager — OAuth Tool Integrations via Composio

Each tenant can connect their own tools (Slack, Google Sheets, HubSpot, etc.)
via OAuth through Composio. This module manages:

1. Available integrations catalog
2. Per-tenant OAuth connection flow
3. Connection status tracking
4. Usage metering per connection
5. MCP URL generation for connected tools

Architecture:
- Composio handles the OAuth flow + token storage
- We map tenant_id → Composio entity_id
- Each connection is scoped to a single tenant
- Admin can see connection status but NEVER OAuth tokens

Usage:
    mgr = ConnectionsManager(tenant_vault, composio_api_key="...")
    mgr.get_available_apps()                        # list all connectable apps
    mgr.initiate_connection("t-123", "slack")       # start OAuth → returns URL
    mgr.get_tenant_connections("t-123")             # list active connections
    mgr.disconnect("t-123", "slack")                # revoke connection
"""

import json
import time
import hashlib
import logging
from typing import Optional
from pathlib import Path
from datetime import datetime

audit_logger = logging.getLogger("vault.audit")


# ================================================================
# AVAILABLE INTEGRATIONS CATALOG
# ================================================================

INTEGRATION_CATALOG = {
    # Communication
    "slack": {
        "name": "Slack",
        "category": "communication",
        "icon": "💬",
        "description": "Send messages, read channels, manage workflows",
        "oauth_scopes": ["channels:read", "chat:write", "users:read"],
        "composio_app": "SLACK",
    },
    "gmail": {
        "name": "Gmail",
        "category": "communication",
        "icon": "📧",
        "description": "Send and read emails, manage labels",
        "oauth_scopes": ["gmail.send", "gmail.readonly"],
        "composio_app": "GMAIL",
    },

    # Spreadsheets & Docs
    "google_sheets": {
        "name": "Google Sheets",
        "category": "data",
        "icon": "📊",
        "description": "Read/write spreadsheets, create reports",
        "oauth_scopes": ["spreadsheets"],
        "composio_app": "GOOGLESHEETS",
    },
    "google_docs": {
        "name": "Google Docs",
        "category": "data",
        "icon": "📄",
        "description": "Create and edit documents",
        "oauth_scopes": ["documents"],
        "composio_app": "GOOGLEDOCS",
    },

    # CRM
    "hubspot": {
        "name": "HubSpot",
        "category": "crm",
        "icon": "🔶",
        "description": "Manage contacts, deals, companies",
        "oauth_scopes": ["crm.objects.contacts.read", "crm.objects.deals.read"],
        "composio_app": "HUBSPOT",
    },
    "salesforce": {
        "name": "Salesforce",
        "category": "crm",
        "icon": "☁️",
        "description": "Access CRM data, manage leads and opportunities",
        "oauth_scopes": ["api", "refresh_token"],
        "composio_app": "SALESFORCE",
    },

    # Sequencing
    "instantly": {
        "name": "Instantly",
        "category": "sequencing",
        "icon": "⚡",
        "description": "Email outreach sequences and campaigns",
        "oauth_scopes": [],
        "composio_app": "INSTANTLY",
    },
    "lemlist": {
        "name": "Lemlist",
        "category": "sequencing",
        "icon": "🍋",
        "description": "Multi-channel outreach campaigns",
        "oauth_scopes": [],
        "composio_app": "LEMLIST",
    },

    # Project Management
    "linear": {
        "name": "Linear",
        "category": "project",
        "icon": "📐",
        "description": "Issue tracking and project management",
        "oauth_scopes": ["read", "write"],
        "composio_app": "LINEAR",
    },
    "notion": {
        "name": "Notion",
        "category": "project",
        "icon": "📝",
        "description": "Databases, pages, and workspace management",
        "oauth_scopes": ["read_content", "update_content"],
        "composio_app": "NOTION",
    },

    # Data & Enrichment (these map to vault proxy keys too)
    "apollo_io": {
        "name": "Apollo.io",
        "category": "enrichment",
        "icon": "🚀",
        "description": "Lead enrichment and prospecting",
        "oauth_scopes": [],
        "composio_app": "APOLLO",
    },
}


class ConnectionsManager:
    """
    Manages per-tenant tool connections via Composio OAuth.

    Each tenant gets a unique entity in Composio, isolating their
    OAuth tokens and connections from other tenants.
    """

    def __init__(self, base_path: Optional[Path] = None, composio_api_key: Optional[str] = None):
        self.base_path = base_path or Path.home() / ".vault"
        self.connections_file = self.base_path / "connections.json"
        self.composio_api_key = composio_api_key
        self._connections: dict = {}
        self._load()

    def _load(self):
        """Load connections registry from disk."""
        if self.connections_file.exists():
            self._connections = json.loads(self.connections_file.read_text())
        else:
            self._connections = {"tenants": {}, "platform_connections": {}}

    def _save(self):
        """Persist connections registry."""
        self.connections_file.parent.mkdir(parents=True, exist_ok=True)
        self.connections_file.write_text(json.dumps(self._connections, indent=2))

    # ================================================================
    # CATALOG
    # ================================================================

    def get_available_apps(self, category: Optional[str] = None) -> dict:
        """List all available integrations, optionally filtered by category."""
        apps = {}
        for app_id, info in INTEGRATION_CATALOG.items():
            if category and info["category"] != category:
                continue
            apps[app_id] = {
                "name": info["name"],
                "category": info["category"],
                "icon": info["icon"],
                "description": info["description"],
            }

        categories = sorted(set(v["category"] for v in INTEGRATION_CATALOG.values()))
        return {
            "success": True,
            "apps": apps,
            "total": len(apps),
            "categories": categories,
        }

    # ================================================================
    # CONNECTION MANAGEMENT
    # ================================================================

    def _get_entity_id(self, tenant_id: str) -> str:
        """Generate a Composio entity ID for a tenant."""
        return f"gtm-{tenant_id}"

    def _get_tenant_data(self, tenant_id: str) -> dict:
        """Get or create tenant connection data."""
        if tenant_id not in self._connections.get("tenants", {}):
            self._connections.setdefault("tenants", {})[tenant_id] = {
                "entity_id": self._get_entity_id(tenant_id),
                "connections": {},
                "usage": {},
                "created": datetime.utcnow().isoformat(),
            }
            self._save()
        return self._connections["tenants"][tenant_id]

    def initiate_connection(self, tenant_id: str, app_id: str,
                            redirect_url: Optional[str] = None) -> dict:
        """
        Start an OAuth connection flow for a tenant.

        If Composio API key is configured, initiates a real OAuth flow.
        Otherwise, returns instructions for manual setup.
        """
        if app_id not in INTEGRATION_CATALOG:
            return {
                "success": False,
                "error": f"Unknown app: {app_id}",
                "available": list(INTEGRATION_CATALOG.keys()),
            }

        app_info = INTEGRATION_CATALOG[app_id]
        tenant_data = self._get_tenant_data(tenant_id)
        entity_id = tenant_data["entity_id"]

        # Try Composio OAuth flow
        if self.composio_api_key:
            try:
                return self._composio_oauth(tenant_id, app_id, entity_id, redirect_url)
            except Exception as e:
                audit_logger.warning(f"Composio OAuth failed for {app_id}: {e}")
                # Fall through to manual flow

        # Manual/API key flow
        tenant_data["connections"][app_id] = {
            "status": "pending",
            "app_name": app_info["name"],
            "category": app_info["category"],
            "initiated_at": datetime.utcnow().isoformat(),
            "method": "manual",
        }
        self._save()

        audit_logger.info(
            f"CONNECTION_INITIATED | tenant={tenant_id} | app={app_id} | method=manual"
        )

        return {
            "success": True,
            "status": "pending",
            "app": app_info["name"],
            "method": "manual",
            "message": f"To connect {app_info['name']}, provide your API key or OAuth token.",
            "composio_setup": {
                "step1": "Set COMPOSIO_API_KEY in your environment",
                "step2": f"Run: composio add {app_info['composio_app'].lower()}",
                "step3": "Complete OAuth in your browser",
                "entity_id": entity_id,
            },
        }

    def complete_connection(self, tenant_id: str, app_id: str,
                            api_key: Optional[str] = None,
                            oauth_token: Optional[str] = None,
                            connection_id: Optional[str] = None) -> dict:
        """
        Complete a pending connection with credentials.

        For API key-based apps: provide api_key
        For OAuth apps: provide oauth_token or connection_id from Composio
        """
        if app_id not in INTEGRATION_CATALOG:
            return {"success": False, "error": f"Unknown app: {app_id}"}

        app_info = INTEGRATION_CATALOG[app_id]
        tenant_data = self._get_tenant_data(tenant_id)

        # Store connection (credentials go to vault, not here)
        credential_fingerprint = None
        if api_key:
            credential_fingerprint = hashlib.sha256(api_key.encode()).hexdigest()[:12]
        elif oauth_token:
            credential_fingerprint = hashlib.sha256(oauth_token.encode()).hexdigest()[:12]
        elif connection_id:
            credential_fingerprint = hashlib.sha256(connection_id.encode()).hexdigest()[:12]

        tenant_data["connections"][app_id] = {
            "status": "active",
            "app_name": app_info["name"],
            "category": app_info["category"],
            "connected_at": datetime.utcnow().isoformat(),
            "credential_fingerprint": credential_fingerprint,
            "connection_id": connection_id,
            "method": "oauth" if oauth_token or connection_id else "api_key",
        }

        # Initialize usage tracking
        tenant_data.setdefault("usage", {})[app_id] = {
            "total_calls": 0,
            "last_call": None,
            "errors": 0,
        }

        self._save()

        audit_logger.info(
            f"CONNECTION_COMPLETED | tenant={tenant_id} | app={app_id} | "
            f"method={'oauth' if oauth_token or connection_id else 'api_key'}"
        )

        return {
            "success": True,
            "app": app_info["name"],
            "status": "active",
            "fingerprint": credential_fingerprint,
            "message": f"{app_info['name']} is now connected and ready to use.",
        }

    # ================================================================
    # TENANT VIEW
    # ================================================================

    def get_tenant_connections(self, tenant_id: str) -> dict:
        """Get all connections for a tenant with status info."""
        tenant_data = self._get_tenant_data(tenant_id)
        connections = []

        for app_id, info in INTEGRATION_CATALOG.items():
            conn = tenant_data.get("connections", {}).get(app_id, {})
            usage = tenant_data.get("usage", {}).get(app_id, {})

            connections.append({
                "app_id": app_id,
                "name": info["name"],
                "icon": info["icon"],
                "category": info["category"],
                "description": info["description"],
                "status": conn.get("status", "not_connected"),
                "connected_at": conn.get("connected_at"),
                "method": conn.get("method"),
                "fingerprint": conn.get("credential_fingerprint"),
                "total_calls": usage.get("total_calls", 0),
                "last_call": usage.get("last_call"),
                "errors": usage.get("errors", 0),
            })

        active = [c for c in connections if c["status"] == "active"]
        pending = [c for c in connections if c["status"] == "pending"]

        return {
            "success": True,
            "connections": connections,
            "summary": {
                "active": len(active),
                "pending": len(pending),
                "available": len(connections) - len(active) - len(pending),
            },
        }

    # ================================================================
    # USAGE TRACKING
    # ================================================================

    def track_usage(self, tenant_id: str, app_id: str, success: bool = True) -> dict:
        """Track a tool usage event for a tenant."""
        tenant_data = self._get_tenant_data(tenant_id)
        usage = tenant_data.setdefault("usage", {}).setdefault(app_id, {
            "total_calls": 0, "last_call": None, "errors": 0,
        })

        usage["total_calls"] = usage.get("total_calls", 0) + 1
        usage["last_call"] = datetime.utcnow().isoformat()
        if not success:
            usage["errors"] = usage.get("errors", 0) + 1

        self._save()
        return {"success": True, "total_calls": usage["total_calls"]}

    def get_tenant_usage(self, tenant_id: str) -> dict:
        """Get detailed usage breakdown for a tenant."""
        tenant_data = self._get_tenant_data(tenant_id)
        usage = tenant_data.get("usage", {})

        # Combine with vault key usage
        breakdown = {}
        total_calls = 0
        total_errors = 0

        for app_id, app_usage in usage.items():
            calls = app_usage.get("total_calls", 0)
            errors = app_usage.get("errors", 0)
            total_calls += calls
            total_errors += errors

            app_info = INTEGRATION_CATALOG.get(app_id, {})
            breakdown[app_id] = {
                "name": app_info.get("name", app_id),
                "icon": app_info.get("icon", "🔧"),
                "category": app_info.get("category", "other"),
                "total_calls": calls,
                "errors": errors,
                "success_rate": f"{((calls - errors) / calls * 100):.1f}%" if calls > 0 else "N/A",
                "last_call": app_usage.get("last_call"),
            }

        return {
            "success": True,
            "tenant_id": tenant_id,
            "total_calls": total_calls,
            "total_errors": total_errors,
            "overall_success_rate": f"{((total_calls - total_errors) / total_calls * 100):.1f}%" if total_calls > 0 else "N/A",
            "breakdown": breakdown,
        }

    # ================================================================
    # ADMIN VIEW
    # ================================================================

    def admin_overview(self) -> dict:
        """Admin view of all tenant connections."""
        tenants = {}
        total_connections = 0
        total_calls = 0

        for tenant_id, data in self._connections.get("tenants", {}).items():
            active_conns = [
                app_id for app_id, conn in data.get("connections", {}).items()
                if conn.get("status") == "active"
            ]
            tenant_calls = sum(
                u.get("total_calls", 0)
                for u in data.get("usage", {}).values()
            )

            total_connections += len(active_conns)
            total_calls += tenant_calls

            tenants[tenant_id] = {
                "entity_id": data.get("entity_id"),
                "active_connections": active_conns,
                "connection_count": len(active_conns),
                "total_calls": tenant_calls,
            }

        return {
            "success": True,
            "tenants": tenants,
            "total_active_connections": total_connections,
            "total_calls": total_calls,
        }

    # ================================================================
    # COMPOSIO INTEGRATION (when API key available)
    # ================================================================

    def _get_composio_client(self):
        """Get a Composio SDK client instance."""
        from composio import Composio
        if not self.composio_api_key:
            raise Exception("Composio API key not configured")
        return Composio(api_key=self.composio_api_key)

    def _composio_oauth(self, tenant_id: str, app_id: str,
                        entity_id: str, redirect_url: Optional[str] = None) -> dict:
        """Initiate OAuth via Composio SDK."""
        app_info = INTEGRATION_CATALOG[app_id]
        composio_app = app_info["composio_app"]

        client = self._get_composio_client()
        entity = client.get_entity(id=entity_id)

        # Initiate connection — returns ConnectionRequestModel with
        # .redirectUrl, .connectedAccountId, .connectionStatus
        callback_url = redirect_url or f"http://localhost:5555/tenant/{tenant_id}/oauth-callback"
        conn_request = entity.initiate_connection(
            app_name=composio_app,
            redirect_url=callback_url,
        )

        # Store pending connection locally
        tenant_data = self._get_tenant_data(tenant_id)
        tenant_data["connections"][app_id] = {
            "status": "pending_oauth",
            "app_name": app_info["name"],
            "category": app_info["category"],
            "initiated_at": datetime.utcnow().isoformat(),
            "method": "oauth",
            "composio_connection_id": conn_request.connectedAccountId,
        }
        self._save()

        audit_logger.info(
            f"OAUTH_INITIATED | tenant={tenant_id} | app={app_id} | "
            f"composio_account={conn_request.connectedAccountId}"
        )

        return {
            "success": True,
            "status": "pending_oauth",
            "oauth_url": conn_request.redirectUrl,
            "connected_account_id": conn_request.connectedAccountId,
            "message": f"Click the link to authorize {app_info['name']}",
        }

    def sync_connection_status(self, tenant_id: str) -> dict:
        """
        Sync local connection status with Composio's real state.
        Called on page load to ensure UI reflects actual OAuth status.
        """
        if not self.composio_api_key:
            return {"success": False, "reason": "no_api_key"}

        tenant_data = self._get_tenant_data(tenant_id)
        entity_id = tenant_data["entity_id"]

        try:
            client = self._get_composio_client()
            entity = client.get_entity(id=entity_id)

            # Get all active connections from Composio
            composio_connections = entity.get_connections()

            # Build a map of composio appUniqueId → connection
            composio_map = {}
            for conn in composio_connections:
                composio_map[conn.appUniqueId.lower()] = conn

            synced = []
            # Update local status for each catalog app
            for app_id, app_info in INTEGRATION_CATALOG.items():
                composio_app_slug = app_info["composio_app"].lower()
                local_conn = tenant_data.get("connections", {}).get(app_id, {})

                if composio_app_slug in composio_map:
                    remote = composio_map[composio_app_slug]
                    # Composio has an active connection — update local
                    if local_conn.get("status") != "active" or not local_conn.get("composio_connection_id"):
                        tenant_data["connections"][app_id] = {
                            "status": "active",
                            "app_name": app_info["name"],
                            "category": app_info["category"],
                            "connected_at": local_conn.get("connected_at", remote.createdAt),
                            "method": "oauth",
                            "composio_connection_id": remote.id,
                            "credential_fingerprint": hashlib.sha256(
                                remote.id.encode()
                            ).hexdigest()[:12],
                        }
                        synced.append(app_id)
                else:
                    # Not in Composio — if local says active via oauth, mark stale
                    if (local_conn.get("status") == "active"
                            and local_conn.get("method") == "oauth"):
                        tenant_data["connections"][app_id]["status"] = "disconnected"
                        synced.append(app_id)
                    elif local_conn.get("status") == "pending_oauth":
                        # Check if the pending connection completed
                        cid = local_conn.get("composio_connection_id")
                        if cid:
                            try:
                                account = client.connected_accounts.get(
                                    connection_id=cid
                                )
                                if account.status == "ACTIVE":
                                    tenant_data["connections"][app_id] = {
                                        "status": "active",
                                        "app_name": app_info["name"],
                                        "category": app_info["category"],
                                        "connected_at": datetime.utcnow().isoformat(),
                                        "method": "oauth",
                                        "composio_connection_id": cid,
                                        "credential_fingerprint": hashlib.sha256(
                                            cid.encode()
                                        ).hexdigest()[:12],
                                    }
                                    synced.append(app_id)
                            except Exception:
                                pass

            if synced:
                self._save()
                audit_logger.info(
                    f"CONNECTION_SYNC | tenant={tenant_id} | synced={synced}"
                )

            return {
                "success": True,
                "synced": synced,
                "composio_active": list(composio_map.keys()),
            }

        except Exception as e:
            audit_logger.warning(f"Connection sync failed for {tenant_id}: {e}")
            return {"success": False, "error": str(e)}

    def resolve_app_from_connection(self, connected_account_id: str) -> Optional[str]:
        """
        Given a Composio connected_account_id, resolve which app_id it maps to.
        Returns our local app_id (e.g., 'slack') or None.
        """
        if not self.composio_api_key:
            return None

        try:
            client = self._get_composio_client()
            account = client.connected_accounts.get(connection_id=connected_account_id)
            composio_slug = account.appUniqueId.lower()

            # Map composio slug back to our catalog app_id
            for app_id, info in INTEGRATION_CATALOG.items():
                if info["composio_app"].lower() == composio_slug:
                    return app_id

            return None
        except Exception as e:
            audit_logger.warning(f"Failed to resolve app from connection {connected_account_id}: {e}")
            return None

    def disconnect(self, tenant_id: str, app_id: str) -> dict:
        """Disconnect a tenant from an app, revoking Composio connection if applicable."""
        tenant_data = self._get_tenant_data(tenant_id)

        if app_id not in tenant_data.get("connections", {}):
            return {"success": False, "error": f"Not connected to {app_id}"}

        conn = tenant_data["connections"].pop(app_id)

        # Revoke Composio connection if it was OAuth-based
        composio_id = conn.get("composio_connection_id")
        if composio_id and self.composio_api_key:
            try:
                client = self._get_composio_client()
                client.http.delete(url=f"/v1/connectedAccounts/{composio_id}")
                audit_logger.info(
                    f"COMPOSIO_REVOKED | tenant={tenant_id} | app={app_id} | "
                    f"connection_id={composio_id}"
                )
            except Exception as e:
                audit_logger.warning(
                    f"Failed to revoke Composio connection {composio_id}: {e}"
                )

        self._save()

        audit_logger.info(f"CONNECTION_REMOVED | tenant={tenant_id} | app={app_id}")

        return {
            "success": True,
            "app": INTEGRATION_CATALOG.get(app_id, {}).get("name", app_id),
            "message": f"Disconnected from {conn.get('app_name', app_id)}.",
        }

    def get_composio_mcp_url(self, tenant_id: str) -> dict:
        """
        Get Composio MCP setup instructions for a tenant.
        Does NOT expose the API key — provides CLI commands instead.
        """
        tenant_data = self._get_tenant_data(tenant_id)
        entity_id = tenant_data["entity_id"]

        if self.composio_api_key:
            return {
                "success": True,
                "entity_id": entity_id,
                "has_api_key": True,
                "setup_command": (
                    f"claude mcp add --transport sse composio-tools "
                    f"'https://backend.composio.dev/v3/mcp/YOUR_KEY/mcp"
                    f"?user_id={entity_id}'"
                ),
                "note": "Replace YOUR_KEY with your Composio API key. "
                        "Never share the full URL — it contains credentials.",
            }
        else:
            return {
                "success": False,
                "error": "Composio API key not configured",
                "entity_id": entity_id,
                "setup_instructions": [
                    "1. Get your API key from app.composio.dev",
                    "2. Set COMPOSIO_API_KEY environment variable",
                    "3. Or pass composio_api_key to ConnectionsManager",
                ],
            }
