"""Configuration commands: get, set."""

from __future__ import annotations

import click

from nrv.utils.config import get_config, load_config, set_config
from nrv.utils.display import print_error, print_json, print_success


@click.group("config")
def config() -> None:
    """Manage nrv configuration."""


@config.command("get")
@click.argument("key", required=False, default=None)
def config_get(key: str | None) -> None:
    """Show all configuration or a specific key.

    Examples:

        nrv config get            # show all
        nrv config get server.url # show one key
    """
    if key is None:
        data = load_config()
        if not data:
            click.echo("No configuration set. Use: nrv config set <key> <value>")
            return
        print_json(data)
    else:
        value = get_config(key)
        if value is None:
            print_error(f"Key '{key}' is not set.")
        else:
            click.echo(f"{key} = {value}")


@config.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str) -> None:
    """Set a configuration value.

    Examples:

        nrv config set server.url https://api.nrv.sh
        nrv config set default_strategy waterfall
    """
    set_config(key, value)
    print_success(f"Set {key} = {value}")
