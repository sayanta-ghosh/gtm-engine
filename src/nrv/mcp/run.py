"""CLI command for `nrv mcp serve`."""

from __future__ import annotations

import click


@click.group("mcp")
def mcp() -> None:
    """MCP (Model Context Protocol) server for Claude integration."""


@mcp.command("serve")
def serve() -> None:
    """Start the nrv MCP server on stdin/stdout.

    \b
    This runs the MCP server that Claude Code can connect to.
    It reads JSON-RPC messages from stdin and writes responses to stdout.

    \b
    Typically you don't run this directly — Claude Code starts it
    automatically via .mcp.json configuration. But you can test it:

        nrv mcp serve

    Then paste JSON-RPC messages on stdin.
    """
    from nrv.mcp.server import main

    main()
