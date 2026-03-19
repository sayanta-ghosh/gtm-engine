# Local Changelog (pending migration to company repo)

All changes below are uncommitted / committed locally but NOT pushed to git.
Push to company repo after cloning.

---

## Pending Changes

### Scripts — Repeatable Workflows
- `scripts/watchlist-digest.py` — Standalone Python script for the LinkedIn GTM watchlist digest
  - Loads watchlist from dataset, searches LinkedIn, post-filters, formats Slack message
  - CLI args: `--hours 48`, `--slack`, `--channel C09LF59HS3H`
  - Can be run standalone: `python scripts/watchlist-digest.py`
  - Or via Claude Code when the user says "run the watchlist"

### Scheduler
- Disabled `gtm-watchlist-daily` — Claude Code's scheduler only works when machine is on + server running
- The script approach is more reliable: user triggers it or a proper server-side cron runs it

### Skills Updated (this session)
- `SKILL.md` — MCP tool preference decision tree, planning rule, scheduling rule, result validation, delivery verification
- `use-cases.md` — LinkedIn Thought Leader Watchlist as use case #5
- `google-search-patterns.md` — No-quote handles, parallel queries[], post-filter docs
- `enrichment.md` — BetterContact waterfall redirect
- `waterfall-enrichment/SKILL.md` — Redirects to BetterContact
- `humanizer/SKILL.md` — New skill for removing AI tone

### Server Fixes (this session)
- `server/auth/flexible.py` — Shared auth module (deduped from 5 routers)
- `server/core/vendor_catalog.py` — INTEGRATED_PROVIDERS vs COMING_SOON_PROVIDERS
- `server/execution/providers/rapidapi_google.py` — Bulk search fix (flatten results)
- `server/data/dataset_router.py` — CSV + metadata endpoints, fixed auth
- `server/execution/runs_router.py` — CSV + metadata endpoints
- `server/execution/column_metadata.py` — Pure-Python column profiler
- `server/console/templates/tenant_dashboard.html` — Tabulator.js, column metadata chips, dataset preview fix
- `src/nrv/mcp/server.py` — nrv_get_run_log tool, auto-naming, required fields fixes
- `src/nrv/cli/status.py` — All 16 vendors grouped by category

### Data
- Dataset "LinkedIn GTM Thought Leaders" cleaned: 33 people with handles, titles, topics
- 16 manually added people (Emilia Korczynska, Davide Grieco, Tim Soulo, Kyle Poyar, etc.)
