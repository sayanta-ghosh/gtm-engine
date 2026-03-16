"""Main Click CLI group — registers all subcommands."""

from __future__ import annotations

import click

from nrv import __version__


@click.group()
@click.version_option(version=__version__, prog_name="nrv")
def cli() -> None:
    """nrv -- agent-native GTM execution platform."""


# ---- Register subcommands ------------------------------------------------

from nrv.cli.init import init  # noqa: E402  — one-command setup
from nrv.cli.auth import auth  # noqa: E402
from nrv.cli.enrich import enrich  # noqa: E402
from nrv.cli.search import search  # noqa: E402
from nrv.cli.query import query  # noqa: E402
from nrv.cli.tables import table  # noqa: E402
from nrv.cli.keys import keys  # noqa: E402
from nrv.cli.credits import credits  # noqa: E402
from nrv.cli.config_cmd import config  # noqa: E402
from nrv.cli.dashboard import dashboard  # noqa: E402
from nrv.cli.setup import setup_claude  # noqa: E402
from nrv.cli.status import status  # noqa: E402
from nrv.cli.web import web  # noqa: E402
from nrv.mcp.run import mcp  # noqa: E402

cli.add_command(init)  # nrv init — primary onboarding entry point
cli.add_command(auth)
cli.add_command(status)
cli.add_command(enrich)
cli.add_command(search)
cli.add_command(query)
cli.add_command(table)
cli.add_command(keys)
cli.add_command(credits)
cli.add_command(config)
cli.add_command(dashboard)
cli.add_command(setup_claude)
cli.add_command(web)
cli.add_command(mcp)
