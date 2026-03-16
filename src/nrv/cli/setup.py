"""Setup Claude Code integration: skills and CLAUDE.md."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from nrv.utils.display import print_success, print_warning


CLAUDE_MD_CONTENT = """\
# nrv — Agent-Native GTM Execution Platform

## Available Commands

Use the `nrv` CLI to enrich contacts, search for prospects, query your GTM
database, and manage dashboards.

### Quick Reference

```bash
# Authentication
nrv auth login          # Log in via browser
nrv auth status         # Check auth status

# Enrichment
nrv enrich person --email user@example.com
nrv enrich company --domain example.com
nrv enrich batch --file leads.csv --strategy waterfall

# Search
nrv search people --title "VP Sales" --industry SaaS --limit 50
nrv search companies --industry fintech --funding "series-b"

# Query
nrv query "SELECT * FROM contacts WHERE company_size > 100 LIMIT 10"

# Tables
nrv table list
nrv table describe contacts

# Keys & Credits
nrv keys list
nrv credits balance
```

## Tips for Claude Code

- Always check `nrv auth status` before running commands.
- Use `--dry-run` on enrich commands to preview without spending credits.
- Prefer `--strategy waterfall` for cost efficiency.
- Use `nrv query` for ad-hoc analysis; results come as structured tables.
"""

NRV_SKILL = """\
---
name: nrv-gtm
description: Interact with the nrv GTM execution platform
---

Use the `nrv` CLI to enrich, search, and query GTM data. Always ensure the
user is authenticated (`nrv auth status`) before running commands.

Key patterns:
- Enrich a person: `nrv enrich person --email X`
- Enrich a company: `nrv enrich company --domain X`
- Search people: `nrv search people --title X`
- Run SQL: `nrv query "SELECT ..."`
"""


@click.command("setup-claude")
@click.option(
    "--project",
    is_flag=True,
    help="Install to project .claude/ instead of global ~/.claude/.",
)
def setup_claude(project: bool) -> None:
    """Install nrv skills and CLAUDE.md for Claude Code."""
    if project:
        base = Path.cwd() / ".claude"
    else:
        base = Path.home() / ".claude"

    # Ensure directories exist
    skills_dir = base / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # Write skill file
    skill_path = skills_dir / "nrv-gtm.md"
    skill_path.write_text(NRV_SKILL)
    print_success(f"Skill installed: {skill_path}")

    # Write CLAUDE.md
    if project:
        claude_md_path = Path.cwd() / "CLAUDE.md"
    else:
        claude_md_path = base / "CLAUDE.md"

    if claude_md_path.exists():
        print_warning(
            f"CLAUDE.md already exists at {claude_md_path}. "
            "Appending nrv section."
        )
        existing = claude_md_path.read_text()
        if "nrv" not in existing.lower():
            claude_md_path.write_text(existing.rstrip() + "\n\n" + CLAUDE_MD_CONTENT)
            print_success("nrv section appended to CLAUDE.md.")
        else:
            print_warning("CLAUDE.md already contains nrv content. Skipping.")
    else:
        claude_md_path.write_text(CLAUDE_MD_CONTENT)
        print_success(f"CLAUDE.md created: {claude_md_path}")

    click.echo("\nClaude Code setup complete.")
