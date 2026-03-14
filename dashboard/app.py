"""
GTM Engine Dashboard — Admin + Tenant Web UI

Lightweight FastAPI app wrapping the vault admin/tenant consoles
plus Composio-powered tool connections per tenant.
"""

import json
import os
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, Request, Form, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

# Load environment variables from .env file
# Check gtm-engine/.env first, then parent Projects/.env
try:
    from dotenv import load_dotenv
    _project_root = Path(__file__).resolve().parent.parent
    _env_file = _project_root / ".env"
    if not _env_file.exists():
        _env_file = _project_root.parent / ".env"
    if _env_file.exists():
        load_dotenv(_env_file)
except ImportError:
    pass  # python-dotenv not installed — rely on env vars being set

from vault.admin import AdminConsole
from vault.tenant_console import TenantConsole
from vault.proxy import PROVIDER_AUTH_CONFIG
from vault.connections import ConnectionsManager, INTEGRATION_CATALOG

app = FastAPI(title="GTM Engine Dashboard")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

# Global state — in production this would be session-based
VAULT_BASE = Path(__file__).parent.parent / ".vault"
admin_console: Optional[AdminConsole] = None
tenant_consoles: dict[str, TenantConsole] = {}
connections_mgr: Optional[ConnectionsManager] = None


def get_admin() -> AdminConsole:
    global admin_console
    if not admin_console:
        admin_console = AdminConsole(base_path=VAULT_BASE)
        try:
            admin_console.unlock("dev-passphrase")
        except Exception:
            pass
    return admin_console


def get_connections() -> ConnectionsManager:
    global connections_mgr
    if not connections_mgr:
        # Support both uppercase and lowercase env var names
        composio_key = (
            os.environ.get("COMPOSIO_API_KEY")
            or os.environ.get("composio_api_key")
        )
        connections_mgr = ConnectionsManager(
            base_path=VAULT_BASE,
            composio_api_key=composio_key,
        )
    return connections_mgr


# ================================================================
# ADMIN ROUTES
# ================================================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    admin = get_admin()
    dash = admin.dashboard()
    platform_keys = admin.list_platform_keys()
    conn_mgr = get_connections()
    conn_overview = conn_mgr.admin_overview()
    return templates.TemplateResponse("admin_dashboard.html", {
        "request": request,
        "dash": dash,
        "platform_keys": platform_keys.get("platform_keys", {}),
        "providers": list(PROVIDER_AUTH_CONFIG.keys()),
        "conn_overview": conn_overview,
    })


@app.post("/admin/add-platform-key")
async def add_platform_key(provider: str = Form(...), key_value: str = Form(...)):
    admin = get_admin()
    admin.add_platform_key(provider, key_value)
    return RedirectResponse("/", status_code=303)


@app.post("/admin/remove-platform-key")
async def remove_platform_key(provider: str = Form(...)):
    admin = get_admin()
    admin.remove_platform_key(provider)
    return RedirectResponse("/", status_code=303)


@app.post("/admin/create-tenant")
async def create_tenant(
    name: str = Form(...),
    passphrase: str = Form(...),
    plan: str = Form("both"),
    spend_cap: str = Form(""),
):
    admin = get_admin()
    cap = int(float(spend_cap) * 100) if spend_cap.strip() else None
    admin.create_tenant(name, passphrase, plan=plan, spend_cap_cents=cap)
    return RedirectResponse("/", status_code=303)


@app.post("/admin/suspend-tenant")
async def suspend_tenant(tenant_id: str = Form(...)):
    admin = get_admin()
    admin.suspend_tenant(tenant_id)
    return RedirectResponse("/", status_code=303)


@app.post("/admin/reactivate-tenant")
async def reactivate_tenant(tenant_id: str = Form(...), passphrase: str = Form(...)):
    admin = get_admin()
    admin.reactivate_tenant(tenant_id, passphrase)
    return RedirectResponse("/", status_code=303)


# ================================================================
# TENANT ROUTES
# ================================================================

@app.get("/tenant/{tenant_id}", response_class=HTMLResponse)
async def tenant_dashboard(request: Request, tenant_id: str, tab: str = "keys"):
    admin = get_admin()
    tenant_info = admin.tv.registry.get("tenants", {}).get(tenant_id)
    if not tenant_info:
        raise HTTPException(404, "Tenant not found")

    # Get or create tenant console
    if tenant_id not in tenant_consoles:
        tc = TenantConsole(admin.tv, tenant_id=tenant_id)
        try:
            tc.unlock(tenant_info.get("_passphrase", "dev-passphrase"))
        except Exception:
            try:
                tc._unlocked = tenant_id in admin.tv._tenant_vaults
            except Exception:
                pass
        tenant_consoles[tenant_id] = tc

    tc = tenant_consoles[tenant_id]

    providers_data = tc.my_providers() if tc._unlocked else {"success": False, "providers": []}
    usage_data = tc.my_usage() if tc._unlocked else {"success": False}
    comparison = tc.byok_vs_platform() if tc._unlocked else {"success": False, "comparison": []}

    # Connections data — sync with Composio first
    conn_mgr = get_connections()
    conn_mgr.sync_connection_status(tenant_id)
    connections_data = conn_mgr.get_tenant_connections(tenant_id)
    conn_usage = conn_mgr.get_tenant_usage(tenant_id)

    # Vault usage (enrichment keys)
    vault_usage = usage_data.get("usage", {}) if usage_data.get("success") else {}

    return templates.TemplateResponse("tenant_dashboard.html", {
        "request": request,
        "tenant_id": tenant_id,
        "tenant_name": tenant_info.get("name", tenant_id),
        "plan": tenant_info.get("plan", "byok"),
        "status": tenant_info.get("status", "active"),
        "providers": providers_data.get("providers", []),
        "summary": providers_data.get("summary", {}),
        "usage": usage_data,
        "vault_usage": vault_usage,
        "comparison": comparison.get("comparison", []),
        "all_providers": list(PROVIDER_AUTH_CONFIG.keys()),
        "unlocked": tc._unlocked,
        "active_tab": tab,
        # Connections
        "connections": connections_data.get("connections", []),
        "conn_summary": connections_data.get("summary", {}),
        "conn_usage": conn_usage,
        "integration_catalog": INTEGRATION_CATALOG,
    })


@app.post("/tenant/{tenant_id}/add-key")
async def tenant_add_key(tenant_id: str, provider: str = Form(...), key_value: str = Form(...)):
    tc = tenant_consoles.get(tenant_id)
    if tc and tc._unlocked:
        tc.use_my_key(provider, key_value)
    return RedirectResponse(f"/tenant/{tenant_id}?tab=keys", status_code=303)


@app.post("/tenant/{tenant_id}/use-platform")
async def tenant_use_platform(tenant_id: str, provider: str = Form(...)):
    tc = tenant_consoles.get(tenant_id)
    if tc and tc._unlocked:
        tc.use_platform_key(provider)
    return RedirectResponse(f"/tenant/{tenant_id}?tab=keys", status_code=303)


@app.post("/tenant/{tenant_id}/rotate-key")
async def tenant_rotate_key(tenant_id: str, provider: str = Form(...), key_value: str = Form(...)):
    tc = tenant_consoles.get(tenant_id)
    if tc and tc._unlocked:
        tc.rotate_my_key(provider, key_value)
    return RedirectResponse(f"/tenant/{tenant_id}?tab=keys", status_code=303)


@app.post("/tenant/{tenant_id}/unlock")
async def tenant_unlock(tenant_id: str, passphrase: str = Form(...)):
    admin = get_admin()
    tc = TenantConsole(admin.tv, tenant_id=tenant_id)
    result = tc.unlock(passphrase)
    if result.get("success"):
        tenant_consoles[tenant_id] = tc
    return RedirectResponse(f"/tenant/{tenant_id}", status_code=303)


# ================================================================
# CONNECTION ROUTES
# ================================================================

@app.post("/tenant/{tenant_id}/connect")
async def tenant_connect_app(request: Request, tenant_id: str, app_id: str = Form(...)):
    """Initiate connection to an app via Composio OAuth."""
    conn_mgr = get_connections()

    # Build callback URL pointing back to our OAuth callback route
    base_url = str(request.base_url).rstrip("/")
    redirect_url = f"{base_url}/tenant/{tenant_id}/oauth-callback"

    result = conn_mgr.initiate_connection(tenant_id, app_id, redirect_url=redirect_url)

    if result.get("oauth_url"):
        # Redirect user to Composio's OAuth consent page
        return RedirectResponse(result["oauth_url"], status_code=303)
    return RedirectResponse(f"/tenant/{tenant_id}?tab=connections", status_code=303)


@app.post("/tenant/{tenant_id}/connect-with-key")
async def tenant_connect_with_key(
    tenant_id: str,
    app_id: str = Form(...),
    api_key: str = Form(...),
):
    """Connect to an app using an API key."""
    conn_mgr = get_connections()
    conn_mgr.complete_connection(tenant_id, app_id, api_key=api_key)
    return RedirectResponse(f"/tenant/{tenant_id}?tab=connections", status_code=303)


@app.post("/tenant/{tenant_id}/disconnect")
async def tenant_disconnect_app(tenant_id: str, app_id: str = Form(...)):
    """Disconnect from an app."""
    conn_mgr = get_connections()
    conn_mgr.disconnect(tenant_id, app_id)
    return RedirectResponse(f"/tenant/{tenant_id}?tab=connections", status_code=303)


@app.get("/tenant/{tenant_id}/oauth-callback")
async def oauth_callback(
    tenant_id: str,
    connected_account_id: str = Query(default=""),
    status: str = Query(default=""),
):
    """
    Handle OAuth callback from Composio.
    Composio redirects back with ?connected_account_id=...&status=...
    """
    conn_mgr = get_connections()

    if status == "success" and connected_account_id:
        # Resolve which app this connection is for
        app_id = conn_mgr.resolve_app_from_connection(connected_account_id)
        if app_id:
            conn_mgr.complete_connection(
                tenant_id, app_id,
                connection_id=connected_account_id,
            )
    else:
        # Even without explicit success, sync will pick up completed connections
        conn_mgr.sync_connection_status(tenant_id)

    return RedirectResponse(f"/tenant/{tenant_id}?tab=connections", status_code=303)


# ================================================================
# API ENDPOINTS
# ================================================================

@app.get("/api/admin/dashboard")
async def api_dashboard():
    admin = get_admin()
    return admin.dashboard()


@app.get("/api/tenant/{tenant_id}/providers")
async def api_tenant_providers(tenant_id: str):
    tc = tenant_consoles.get(tenant_id)
    if not tc or not tc._unlocked:
        return {"success": False, "error": "Tenant not unlocked"}
    return tc.my_providers()


@app.get("/api/tenant/{tenant_id}/connections")
async def api_tenant_connections(tenant_id: str):
    conn_mgr = get_connections()
    return conn_mgr.get_tenant_connections(tenant_id)


@app.get("/api/tenant/{tenant_id}/usage")
async def api_tenant_usage(tenant_id: str):
    conn_mgr = get_connections()
    return conn_mgr.get_tenant_usage(tenant_id)


@app.post("/api/tenant/{tenant_id}/track-usage")
async def api_track_usage(tenant_id: str, app_id: str = Form(...), count: int = Form(1), errors: int = Form(0)):
    """Track usage events for a tenant's connected tool."""
    conn_mgr = get_connections()
    for _ in range(count - errors):
        conn_mgr.track_usage(tenant_id, app_id, success=True)
    for _ in range(errors):
        conn_mgr.track_usage(tenant_id, app_id, success=False)
    return {"success": True, "tracked": count}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5555)
