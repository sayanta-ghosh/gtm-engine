"""
gtm connect — Connect an OAuth app via Composio

Opens a browser for OAuth consent flow.
"""

import sys
import json
import click
from pathlib import Path

from ..config import load_config, resolve_passphrase
from ..output import console, print_success, print_error, print_info


@click.command()
@click.argument("app", required=False, default=None)
@click.option("--list", "list_apps", is_flag=True, help="List all available apps")
@click.option("--disconnect", is_flag=True, help="Disconnect instead of connect")
@click.option("--passphrase", default=None, help="Vault passphrase")
def connect(app, list_apps, disconnect, passphrase):
    """Connect an OAuth app (Slack, Sheets, HubSpot, etc.)

    Examples:
        gtm connect --list
        gtm connect slack
        gtm connect google_sheets
        gtm connect --disconnect slack
    """
    config = load_config()
    tenant_id = config.get("tenant_id")
    vault_base = config.get("vault_base")
    project_root = config.get("project_root")

    if not tenant_id:
        print_error("No tenant configured. Run 'gtm init' first.")
        raise SystemExit(1)

    try:
        sys.path.insert(0, str(project_root or Path(__file__).resolve().parent.parent.parent))
        from vault.connections import ConnectionsManager, INTEGRATION_CATALOG

        import os
        composio_key = os.environ.get("COMPOSIO_API_KEY") or os.environ.get("composio_api_key")

        conn_mgr = ConnectionsManager(
            base_path=Path(vault_base) if vault_base else None,
            composio_api_key=composio_key,
        )

        if list_apps:
            console.print()
            console.print("  [bold cyan]Available Apps[/bold cyan]")
            console.print()
            for app_id, info in INTEGRATION_CATALOG.items():
                status_str = ""
                conns = conn_mgr.get_tenant_connections(tenant_id)
                for c in conns.get("connections", []):
                    if c["app_id"] == app_id and c["status"] == "active":
                        status_str = " [green](connected)[/green]"
                        break
                console.print(
                    f"    {info.get('icon', '')}  [bold]{app_id:<18}[/bold] "
                    f"{info.get('name', ''):<20} "
                    f"[dim]{info.get('category', '')}[/dim]"
                    f"{status_str}"
                )
            console.print()
            return

        if not app:
            print_error("Specify an app to connect. Use --list to see available apps.")
            raise SystemExit(1)

        app = app.lower().strip()

        if disconnect:
            result = conn_mgr.disconnect(tenant_id, app)
            if result.get("success"):
                print_success(f"Disconnected from {app}")
            else:
                print_error(f"Failed: {result.get('error', 'Unknown error')}")
            return

        # Initiate connection
        result = conn_mgr.initiate_connection(tenant_id, app)

        if result.get("oauth_url"):
            print_success(f"Opening OAuth for {app}...")
            console.print(f"  URL: [link={result['oauth_url']}]{result['oauth_url']}[/link]")
            console.print()

            # Try to open browser
            try:
                import webbrowser
                webbrowser.open(result["oauth_url"])
                print_info("Browser opened. Complete the OAuth flow, then check your dashboard.")
            except Exception:
                print_info("Open the URL above in your browser to complete the OAuth flow.")
        elif result.get("method") == "manual":
            print_info(f"No Composio API key set. Manual setup required for {app}.")
            setup = result.get("composio_setup", {})
            if setup:
                console.print(f"  Setup: {setup.get('instruction', '')}")
        else:
            print_error(f"Failed: {result.get('error', 'Unknown error')}")

    except ImportError as e:
        print_error(f"Cannot import modules: {e}")
        raise SystemExit(1)
    except Exception as e:
        print_error(f"Error: {e}")
        raise SystemExit(1)
