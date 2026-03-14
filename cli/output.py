"""
Rich Terminal Output Helpers

Consistent formatting for CLI output using the Rich library.
"""

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text
from rich import box

console = Console()


def print_success(message: str):
    """Print a success message."""
    console.print(f"  [green bold]\u2713[/green bold] {message}")


def print_error(message: str):
    """Print an error message."""
    console.print(f"  [red bold]\u2717[/red bold] {message}")


def print_warning(message: str):
    """Print a warning message."""
    console.print(f"  [yellow bold]![/yellow bold] {message}")


def print_info(message: str):
    """Print an info message."""
    console.print(f"  [dim]{message}[/dim]")


def print_header(title: str, subtitle: str = ""):
    """Print a styled header."""
    text = Text(title, style="bold cyan")
    if subtitle:
        text.append(f"\n{subtitle}", style="dim")
    console.print(Panel(text, box=box.ROUNDED, padding=(0, 2)))


def print_divider():
    """Print a subtle divider."""
    console.print("[dim]" + "\u2500" * 50 + "[/dim]")


def provider_table(providers: list, title: str = "Providers") -> Table:
    """Create a styled provider status table."""
    table = Table(
        title=title,
        box=box.ROUNDED,
        show_header=True,
        header_style="bold",
        title_style="bold cyan",
    )
    table.add_column("Provider", style="bold")
    table.add_column("Source", justify="center")
    table.add_column("Calls", justify="right")
    table.add_column("Hit Rate", justify="right")
    table.add_column("Avg Cost", justify="right")

    for p in providers:
        source = p.get("source", "none")
        source_style = {
            "byok": "[green]byok[/green]",
            "platform": "[blue]platform[/blue]",
        }.get(source, "[dim]none[/dim]")

        calls = p.get("total_calls", 0)
        hit_rate = p.get("hit_rate")
        avg_cost = p.get("avg_cost")

        hit_str = f"{hit_rate:.1f}%" if hit_rate is not None and hit_rate > 0 else "[dim]-[/dim]"
        cost_str = f"${avg_cost:.3f}" if avg_cost is not None and avg_cost > 0 else "[dim]-[/dim]"

        table.add_row(
            p.get("provider", "?"),
            source_style,
            str(calls) if calls > 0 else "[dim]0[/dim]",
            hit_str,
            cost_str,
        )

    return table


def intelligence_panel(summary: dict) -> Panel:
    """Create an intelligence summary panel."""
    total = summary.get("total_enriched", 0)
    cost = summary.get("total_cost", 0)
    days = summary.get("days_active", 0)

    lines = []
    if total > 0:
        lines.append(f"Total enriched: [bold]{total:,}[/bold] contacts for [bold]${cost:.2f}[/bold]")
        if days > 0:
            lines.append(f"Active for [bold]{days:.0f}[/bold] days")

        # Find best provider by hit rate
        providers = summary.get("providers", {})
        if providers:
            best = max(
                providers.items(),
                key=lambda x: x[1].get("hit_rate", 0),
                default=None,
            )
            if best and best[1].get("hit_rate", 0) > 0:
                lines.append(
                    f"Best hit rate: [green]{best[0]}[/green] "
                    f"({best[1]['hit_rate']:.1f}%, ${best[1]['avg_cost']:.3f}/rec)"
                )
    else:
        lines.append("[dim]No enrichment data yet. Run some enrichments to build intelligence.[/dim]")

    content = "\n".join(lines)
    return Panel(content, title="Intelligence", box=box.ROUNDED, title_align="left")


def cost_estimate(provider: str, records: int = 1, per_record_cents: float = 3.0) -> str:
    """Format a cost estimate string."""
    total = records * per_record_cents / 100
    if records == 1:
        return f"Estimated cost: ~${total:.2f}"
    return f"Estimated cost: ~${total:.2f} ({records} records x ${per_record_cents/100:.3f}/rec)"


def enrichment_receipt(
    provider: str,
    records: int,
    hits: int,
    cost_cents: float,
    duration_secs: float = 0,
) -> Panel:
    """Create a receipt panel after enrichment."""
    hit_rate = (hits / records * 100) if records > 0 else 0
    cost = cost_cents / 100

    lines = [
        f"Provider:  [bold]{provider}[/bold]",
        f"Records:   {records}",
        f"Hits:      {hits} ({hit_rate:.1f}% hit rate)",
        f"Cost:      [bold]${cost:.2f}[/bold]",
    ]
    if duration_secs > 0:
        lines.append(f"Duration:  {duration_secs:.1f}s")

    content = "\n".join(lines)
    return Panel(content, title="Enrichment Receipt", box=box.ROUNDED, title_align="left", border_style="green")
