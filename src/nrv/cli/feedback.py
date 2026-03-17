"""Feedback command: submit feedback, bugs, and feature requests."""

from __future__ import annotations
import sys

import click

from nrv.client.http import NrvApiError, NrvClient
from nrv.utils.display import print_error, print_success, spinner


def _require_auth() -> None:
    from nrv.client.auth import is_authenticated
    if not is_authenticated():
        print_error("Not logged in. Run: nrv auth login")
        sys.exit(1)


@click.command("feedback")
@click.option("--message", "-m", prompt="Your feedback", help="Feedback message.")
@click.option(
    "--type", "fb_type",
    type=click.Choice(["feedback", "bug", "feature"]),
    default="feedback",
    help="Type of feedback.",
)
def feedback(message: str, fb_type: str) -> None:
    """Submit feedback, bug reports, or feature requests."""
    _require_auth()
    client = NrvClient()
    try:
        with spinner("Sending feedback..."):
            client.post("/feedback", json={"message": message, "type": fb_type})
    except NrvApiError as exc:
        print_error(f"Failed to send feedback: {exc.message}")
        sys.exit(1)
    print_success(f"Thank you! Your {fb_type} has been submitted.")
