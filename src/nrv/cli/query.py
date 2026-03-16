"""Query command: execute SQL against nrv tables."""

from __future__ import annotations

import sys

import click

from nrv.client.http import NrvApiError, NrvClient
from nrv.utils.display import print_error, print_json, print_table, spinner


def _require_auth() -> None:
    from nrv.client.auth import is_authenticated

    if not is_authenticated():
        print_error("Not logged in. Run: nrv auth login")
        sys.exit(1)


@click.command("query")
@click.argument("sql")
def query(sql: str) -> None:
    """Execute a SQL query and display results.

    Example: nrv query "SELECT * FROM contacts LIMIT 10"
    """
    _require_auth()
    client = NrvClient()

    try:
        with spinner("Running query..."):
            result = client.query(sql)
    except NrvApiError as exc:
        print_error(f"Query failed: {exc.message}")
        sys.exit(1)

    columns = result.get("columns", [])
    rows = result.get("rows", [])

    if columns and rows:
        print_table(columns, rows, title="Query Results")
        click.echo(f"\n{len(rows)} row(s) returned")
    elif columns:
        click.echo("Query returned no rows.")
    else:
        # Fallback for non-SELECT or unexpected shape
        print_json(result)
