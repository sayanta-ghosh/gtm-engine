"""
GTM Engine CLI — Main entry point

Usage:
    gtm --help
    gtm init
    gtm add-key apollo
    gtm status
    gtm enrich --provider apollo --email jane@acme.com
    gtm dashboard
    gtm connect slack
    gtm setup-claude
"""

import click

from .commands.init_cmd import init_cmd
from .commands.add_key import add_key
from .commands.status import status
from .commands.enrich import enrich
from .commands.dashboard_cmd import dashboard
from .commands.connect import connect
from .commands.setup_claude import setup_claude


@click.group()
@click.version_option(version="0.1.0", prog_name="gtm-engine")
def cli():
    """GTM Engine - AI-native go-to-market toolkit by nRev.

    Secure API vault, enrichment proxy, and intelligence tracking
    for Claude Code and terminal workflows.
    """
    pass


cli.add_command(init_cmd, "init")
cli.add_command(add_key, "add-key")
cli.add_command(status, "status")
cli.add_command(enrich, "enrich")
cli.add_command(dashboard, "dashboard")
cli.add_command(connect, "connect")
cli.add_command(setup_claude, "setup-claude")


if __name__ == "__main__":
    cli()
