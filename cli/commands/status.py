"""
gtm status — Show vault health, provider status, and intelligence stats

The differentiator: shows hit rates, costs, and provider performance
that accumulate over time (compound intelligence).
"""

import sys
import json
import click
from pathlib import Path

from ..config import load_config, resolve_passphrase, get_intelligence_summary
from ..output import (
    console, print_error, print_header, print_info,
    provider_table, intelligence_panel,
)


@click.command()
@click.option("--json-output", "as_json", is_flag=True, help="Output raw JSON")
@click.option("--passphrase", default=None, help="Vault passphrase")
def status(as_json, passphrase):
    """Show vault health, provider status, and intelligence."""
    config = load_config()
    tenant_id = config.get("tenant_id")
    vault_base = config.get("vault_base")
    project_root = config.get("project_root")
    tenant_name = config.get("tenant_name", tenant_id or "Unknown")

    if not tenant_id:
        print_error("No tenant configured. Run 'gtm init' first.")
        raise SystemExit(1)

    passphrase = resolve_passphrase(passphrase)
    if not passphrase:
        passphrase = click.prompt("Vault passphrase", hide_input=True)

    try:
        sys.path.insert(0, str(project_root or Path(__file__).resolve().parent.parent.parent))
        from vault.tenant import TenantVault
        from vault.key_manager import KeyManager

        tv = TenantVault(base_path=Path(vault_base) if vault_base else None)
        tv.unlock_tenant(tenant_id, passphrase)
        km = KeyManager(tv)

        keys_data = km.show_keys(tenant_id)
        usage_data = km.show_usage(tenant_id)
        intel_summary = get_intelligence_summary()

        if as_json:
            output = {
                "tenant_id": tenant_id,
                "tenant_name": tenant_name,
                "keys": keys_data,
                "usage": usage_data,
                "intelligence": intel_summary,
            }
            click.echo(json.dumps(output, indent=2))
            return

        # Rich output
        print_header(
            f"GTM Engine Status -- {tenant_name}",
            f"Tenant: {tenant_id[:20]}..."
        )
        console.print()

        if keys_data.get("success"):
            providers = keys_data.get("providers", [])
            summary = keys_data.get("summary", {})

            # Merge intelligence data into provider list
            intel_providers = intel_summary.get("providers", {})
            for p in providers:
                name = p["provider"]
                if name in intel_providers:
                    ip = intel_providers[name]
                    p["hit_rate"] = ip.get("hit_rate", 0)
                    p["avg_cost"] = ip.get("avg_cost", 0)

            table = provider_table(providers)
            console.print(table)

            console.print()
            byok = summary.get("byok", 0)
            platform = summary.get("platform", 0)
            total = summary.get("total_available", 0)
            console.print(
                f"  Summary: [green]{byok} BYOK[/green] | "
                f"[blue]{platform} Platform[/blue] | "
                f"[dim]{total} Total Available[/dim]"
            )
        else:
            print_error(f"Could not load keys: {keys_data.get('error')}")

        # Intelligence panel
        console.print()
        panel = intelligence_panel(intel_summary)
        console.print(panel)

        # Dashboard hint
        console.print()
        port = config.get("dashboard_port", 5555)
        print_info(f"Dashboard: http://localhost:{port}")
        console.print()

    except ImportError as e:
        print_error(f"Cannot import vault modules: {e}")
        raise SystemExit(1)
    except Exception as e:
        print_error(f"Error: {e}")
        raise SystemExit(1)
