"""
gtm dashboard — Launch the web dashboard

Starts the FastAPI dashboard on localhost (default port 5555).
"""

import sys
import click
from pathlib import Path

from ..config import load_config
from ..output import console, print_success, print_error, print_info


@click.command()
@click.option("--port", default=5555, type=int, help="Port number [default: 5555]")
@click.option("--host", default="0.0.0.0", help="Host to bind [default: 0.0.0.0]")
@click.option("--open", "open_browser", is_flag=True, help="Open browser automatically")
def dashboard(port, host, open_browser):
    """Launch the web dashboard."""
    config = load_config()
    project_root = config.get("project_root")

    if not project_root:
        # Try to find it
        project_root = str(Path(__file__).resolve().parent.parent.parent)

    sys.path.insert(0, project_root)

    console.print()
    print_success(f"Starting dashboard at [bold]http://localhost:{port}[/bold]")
    print_info("Press Ctrl+C to stop")
    console.print()

    if open_browser:
        import webbrowser
        webbrowser.open(f"http://localhost:{port}")

    try:
        import uvicorn
        uvicorn.run(
            "dashboard.app:app",
            host=host,
            port=port,
            log_level="info",
        )
    except ImportError:
        print_error("uvicorn not installed. Run: pip install uvicorn")
        raise SystemExit(1)
    except KeyboardInterrupt:
        console.print()
        print_info("Dashboard stopped.")
