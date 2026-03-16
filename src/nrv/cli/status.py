"""Status command: one-glance view of auth, keys, credits, and providers."""

from __future__ import annotations

import sys
import time

import click

from nrv.client.auth import is_authenticated, load_credentials
from nrv.client.http import NrvApiError, NrvClient
from nrv.utils.config import get_api_base_url
from nrv.utils.display import console, print_error, print_warning, spinner

from rich.panel import Panel
from rich.table import Table
from rich import box


@click.command("status")
def status() -> None:
    """Show a full overview: auth, providers, credits, and server health."""
    base_url = get_api_base_url()

    # ---- Auth ----
    creds = load_credentials()
    if creds is None:
        console.print(
            Panel(
                "[red bold]Not logged in[/red bold]\n\n"
                "Run [cyan]nrv auth login[/cyan] to get started.\n"
                f"Server: {base_url}",
                title="nrv status",
                border_style="red",
            )
        )
        return

    user_info = creds.get("user_info", {})
    email = user_info.get("email", "unknown")
    tenant = user_info.get("tenant", "unknown")
    expires_at = creds.get("expires_at", 0)
    token_status = "valid" if time.time() < expires_at else "expired (will auto-refresh)"

    # ---- Server health ----
    server_ok = False
    try:
        import httpx

        r = httpx.get(f"{base_url}/health", timeout=5)
        server_ok = r.status_code == 200
        server_version = r.json().get("version", "?") if server_ok else "?"
    except Exception:
        server_version = "unreachable"

    # ---- Build auth section ----
    lines = [
        f"[bold]Email:[/bold]   {email}",
        f"[bold]Tenant:[/bold]  {tenant}",
        f"[bold]Token:[/bold]   {token_status}",
        f"[bold]Server:[/bold]  {base_url} ({'[green]online[/green] v' + server_version if server_ok else '[red]offline[/red]'})",
    ]

    if not server_ok:
        console.print(
            Panel(
                "\n".join(lines) + "\n\n[red]Server is not reachable.[/red]",
                title="nrv status",
                border_style="yellow",
            )
        )
        return

    if not is_authenticated():
        console.print(Panel("\n".join(lines), title="nrv status", border_style="yellow"))
        return

    # ---- Fetch keys + credits from server ----
    client = NrvClient(base_url=base_url)
    keys_data: list[dict] = []
    balance = 0.0
    spend = 0.0

    try:
        with spinner("Fetching account details..."):
            try:
                keys_result = client.list_keys()
                keys_data = keys_result.get("keys", [])
            except NrvApiError:
                pass

            try:
                credits_result = client.get_credits()
                balance = credits_result.get("balance", 0)
                spend = credits_result.get("spend_this_month", 0)
            except NrvApiError:
                pass
    except Exception:
        pass

    # ---- Credits line ----
    if balance > 100:
        bal_style = "green"
    elif balance > 20:
        bal_style = "yellow"
    else:
        bal_style = "red"
    lines.append(f"[bold]Credits:[/bold] [{bal_style}]{balance:,.0f}[/{bal_style}] (spent this month: {spend:,.2f})")

    # ---- Keys table ----
    if keys_data:
        lines.append("")
        lines.append("[bold]API Keys (BYOK):[/bold]")
        for k in keys_data:
            provider = k.get("provider", "?")
            hint = k.get("key_hint", k.get("hint", "****"))
            lines.append(f"  [cyan]{provider:15}[/cyan] ...{hint}")
    else:
        lines.append("")
        lines.append("[dim]No BYOK keys configured. Run: nrv keys add <provider>[/dim]")

    # ---- Available providers ----
    lines.append("")
    providers_info = [
        ("apollo", "Enrich + Search people/companies"),
        ("rocketreach", "Enrich + Search with school/alumni filters"),
        ("predictleads", "Company jobs, news, similar companies"),
    ]
    lines.append("[bold]Available Providers:[/bold]")
    for prov, desc in providers_info:
        has_key = any(k.get("provider") == prov for k in keys_data)
        key_badge = "[green]BYOK[/green]" if has_key else "[dim]platform[/dim]"
        lines.append(f"  [cyan]{prov:15}[/cyan] {key_badge}  {desc}")

    # ---- Quick start hints ----
    lines.append("")
    lines.append("[bold]Quick Start:[/bold]")
    lines.append("  [cyan]nrv search people --title 'VP Sales' --domain stripe.com[/cyan]")
    lines.append("  [cyan]nrv enrich person --email john@acme.com[/cyan]")
    lines.append("  [cyan]nrv enrich company --domain stripe.com[/cyan]")
    lines.append("  [cyan]nrv keys add apollo[/cyan]  (use your own key for free calls)")

    console.print(Panel("\n".join(lines), title="[bold]nrv status[/bold]", border_style="green"))
