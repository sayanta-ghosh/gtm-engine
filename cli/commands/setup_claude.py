"""
gtm setup-claude — Auto-configure Claude Code integration

This is the bridge command that makes Claude Code "GTM-smart".
It generates:
1. .mcp.json — MCP server configuration
2. CLAUDE.md — Always-loaded context (copied from project root)
3. .claude/skills/ — 10 on-demand skill files
4. .claude/rules/ — Security and enrichment rules
"""

import json
import os
import click
from pathlib import Path

from ..config import load_config
from ..output import console, print_success, print_error, print_info, print_header


@click.command()
@click.option("--project-dir", default=".", help="Project directory [default: current]")
@click.option("--tenant-id", default=None, help="Override tenant ID from config")
@click.option("--dry-run", is_flag=True, help="Show what would be written without writing")
@click.option("--force", is_flag=True, help="Overwrite existing files")
def setup_claude(project_dir, tenant_id, dry_run, force):
    """Auto-configure Claude Code with GTM Engine integration.

    Generates .mcp.json, CLAUDE.md, skills, and rules so Claude Code
    immediately knows how to use your GTM Engine tools.
    """
    config = load_config()
    tenant_id = tenant_id or config.get("tenant_id")
    project_root = config.get("project_root")

    if not tenant_id:
        print_error("No tenant configured. Run 'gtm init' first.")
        raise SystemExit(1)

    if not project_root:
        project_root = str(Path(__file__).resolve().parent.parent.parent)

    target_dir = Path(project_dir).resolve()

    print_header("Claude Code Setup", "Configuring GTM Engine integration")
    console.print()

    if dry_run:
        print_info("DRY RUN — no files will be written")
        console.print()

    files_written = 0

    # 1. .mcp.json
    mcp_config = _generate_mcp_json(tenant_id, project_root)
    files_written += _write_file(
        target_dir / ".mcp.json",
        json.dumps(mcp_config, indent=2) + "\n",
        "MCP server configured",
        dry_run, force,
    )

    # 2. CLAUDE.md
    claude_md = _generate_claude_md(tenant_id, project_root)
    files_written += _write_file(
        target_dir / "CLAUDE.md",
        claude_md,
        "GTM context loaded",
        dry_run, force,
    )

    # 3. Skills
    skills = _generate_skills()
    skills_dir = target_dir / ".claude" / "skills"
    for skill_name, content in skills.items():
        skill_dir = skills_dir / skill_name
        files_written += _write_file(
            skill_dir / "SKILL.md",
            content,
            None,  # Don't print per-file
            dry_run, force,
        )
    if files_written > 0 or dry_run:
        print_success(f".claude/skills/     ({len(skills)} skills installed)")

    # 4. Rules
    rules = _generate_rules()
    rules_dir = target_dir / ".claude" / "rules"
    for rule_name, content in rules.items():
        files_written += _write_file(
            rules_dir / rule_name,
            content,
            None,
            dry_run, force,
        )
    print_success(f".claude/rules/      ({len(rules)} rules)")

    console.print()
    if dry_run:
        print_info(f"Would write {files_written} files. Run without --dry-run to apply.")
    else:
        print_success(f"Claude Code configured! ({files_written} files)")
        console.print()
        console.print("  [bold cyan]Next:[/bold cyan]")
        console.print("    Restart Claude Code to load the new MCP server.")
        console.print()
        console.print("  [bold cyan]Try saying:[/bold cyan]")
        console.print('    "Show me my GTM engine status"')
        console.print('    "Enrich jane@acme.com using Apollo"')
        console.print('    "Find email addresses at stripe.com"')
    console.print()


def _write_file(path: Path, content: str, success_msg: str = None,
                dry_run: bool = False, force: bool = False) -> int:
    """Write a file, handling dry-run and force flags. Returns 1 if written."""
    if dry_run:
        if success_msg:
            print_success(f"{success_msg} [dim](dry-run)[/dim]")
        return 1

    if path.exists() and not force:
        if success_msg:
            print_info(f"{path.name} already exists (use --force to overwrite)")
        return 0

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    if success_msg:
        print_success(success_msg)
    return 1


def _generate_mcp_json(tenant_id: str, project_root: str) -> dict:
    """Generate .mcp.json config."""
    config = {
        "mcpServers": {
            "gtm-vault": {
                "command": "python3",
                "args": [
                    "-m", "vault.mcp_server",
                    "--tenant-id", tenant_id,
                    "--passphrase", "${GTM_PASSPHRASE}",
                ],
                "cwd": project_root,
                "env": {
                    "PYTHONPATH": project_root,
                },
            }
        }
    }

    # Add Composio MCP if key is available
    composio_key = os.environ.get("COMPOSIO_API_KEY") or os.environ.get("composio_api_key")
    if composio_key:
        entity_id = f"gtm-{tenant_id}"
        config["mcpServers"]["composio-tools"] = {
            "type": "sse",
            "url": f"https://backend.composio.dev/v3/mcp/${{COMPOSIO_API_KEY}}/mcp?user_id={entity_id}",
        }

    return config


def _generate_claude_md(tenant_id: str, project_root: str) -> str:
    """Generate CLAUDE.md content (~130 lines), personalized from onboarding."""
    config = load_config()
    onboarding = config.get("onboarding", {})

    # Build personalized context section if onboarding data exists
    personalized_section = ""
    if onboarding:
        company = onboarding.get("company_name", "")
        domain = onboarding.get("company_domain", "")
        icp = onboarding.get("icp", {})
        titles = onboarding.get("target_titles", [])
        goals = onboarding.get("goals", [])
        workflows = onboarding.get("recommended_workflows", [])

        personalized_section = f"""
## Your GTM Profile

- Company: {company}{f' ({domain})' if domain else ''}
- ICP: {icp.get('label', 'Custom')} — {', '.join(titles) if titles else 'various titles'}
- Goals: {'; '.join(goals) if goals else 'general GTM'}
- Recommended workflows: {', '.join(workflows) if workflows else 'prospect research, enrichment'}

When the user asks for help with GTM tasks, use this profile to:
- Default to their ICP when searching for prospects
- Suggest their target titles when building lists
- Recommend their preferred workflows first
"""

    return f"""# GTM Engine by nRev

You have access to a secure go-to-market engine that enriches prospects,
manages API keys, and connects to sales tools. This project is the core
infrastructure for nrev.ai.

## Architecture

- vault/ -- Encrypted multi-tenant API key vault (AES-256, PBKDF2 600K iterations)
- cli/ -- Click-based CLI (`gtm` command)
- dashboard/ -- FastAPI web UI on localhost:5555
- .vault/ -- Encrypted key storage (NEVER read or modify directly)
{personalized_section}
## MCP Tools Available

You have 7 MCP tools via the gtm-vault server:

| Tool | Purpose |
|------|---------|
| gtm_vault_status | Check which providers have keys and their status |
| gtm_add_key | Store a BYOK API key (encrypted, never retrievable) |
| gtm_remove_key | Remove a BYOK key (falls back to platform) |
| gtm_show_keys | List key configs with fingerprints (never values) |
| gtm_enrich | Make authenticated API calls via secure proxy |
| gtm_show_usage | Show API call statistics per provider |
| gtm_supported_providers | List all supported providers and auth methods |

## Key Resolution Order

When you call gtm_enrich, the key is resolved automatically:
1. BYOK (tenant's own key) -- used first if available
2. Platform key (shared pool) -- fallback
3. Error -- no key available, tell user to add one

You NEVER see the actual API key. The proxy injects it internally.

## Supported Providers

| Provider | What It Does | Key Endpoints |
|----------|-------------|---------------|
| apollo | People search, enrichment, org data | /people/match, /mixed_people/search, /organizations/enrich |
| rocketreach | Contact info, email/phone finding | /lookupProfile, /search |
| rapidapi_google | Google search via RapidAPI | / (search query) |
| parallel | AI-powered web research | /research |
| pdl | Person + company enrichment | /person/enrich, /company/enrich |
| hunter | Email finding + verification | /domain-search, /email-finder, /email-verifier |
| zerobounce | Email validation | /validate |
| apify | Web scraping actors | /acts/{{actorId}}/runs |
| firecrawl | Web crawling + scraping | /scrape, /crawl |
| instantly | Email sequences | /campaign/list, /lead/add |
| crustdata | Company data enrichment | /screener/screen |
| composio | OAuth tool connections | /connectedAccounts |
| leadmagic | B2B data enrichment | /enrich |

## Intelligence System

Check ~/.gtm/intelligence.json for provider hit rates and cost data.
Use this to recommend the best provider or waterfall order for the user's task.
When multiple providers can do the same job, prefer the one with the highest
hit rate and lowest cost for the user's ICP segment.

## Common Workflows

### Enrich a Person by Email
```
result = gtm_enrich(provider="apollo", endpoint="/people/match",
                     data={{"email": "jane@acme.com"}})
```

### Search for People at a Company
```
result = gtm_enrich(provider="apollo", endpoint="/mixed_people/search",
                     data={{"organization_domains": ["acme.com"],
                           "person_titles": ["VP Sales"]}})
```

### Find Emails for a Domain
```
result = gtm_enrich(provider="hunter", method="GET", endpoint="/domain-search",
                     params={{"domain": "acme.com"}})
```

### Waterfall Enrichment (try multiple providers)
Try apollo first, then rocketreach, then pdl. Stop when you get data.
See skill: waterfall-enrichment for the full strategy.

## Cost Awareness

ALWAYS estimate cost before batch operations and tell the user what they'll spend:
- Apollo: ~$0.03/enrichment
- RocketReach: ~$0.04/enrichment
- PDL: ~$0.05/enrichment
- Hunter: ~$0.015/request
- ZeroBounce: ~$0.01/verification

For batch operations (>10 records), show: "Estimated cost: ~$X.XX for N records"
After completion, show: "Done: N records for $X.XX (Y% hit rate)"

## Security Rules

- NEVER attempt to read files in .vault/ directly
- NEVER log, print, or include API key values in responses
- NEVER pass raw key values through gtm_enrich -- keys are injected by the proxy
- All key operations return fingerprints only
- If a user shares a key in chat, store it immediately via gtm_add_key
  and remind them to rotate it (it appeared in conversation context)

## CLI Quick Reference

| Command | What It Does |
|---------|-------------|
| gtm init | Onboard: create tenant + vault |
| gtm add-key <provider> | Store a BYOK API key |
| gtm status | Show vault health + provider status + intelligence |
| gtm enrich --provider X | Quick enrichment from terminal |
| gtm dashboard | Launch web dashboard |
| gtm connect <app> | OAuth connect to a tool |
| gtm setup-claude | Auto-configure Claude Code integration |

## When to Load Skills

- User asks about Apollo API details -> load apollo-enrichment skill
- User asks about RocketReach -> load rocketreach-enrichment skill
- User asks about finding emails -> load hunter-emails or rocketreach skill
- User asks about enrichment strategy -> load waterfall-enrichment skill
- User asks about connecting tools -> load composio-connections skill
- User asks about building prospect lists -> load list-building skill
- User asks about email campaigns -> load instantly-campaigns skill
- User asks about scraping -> load scraping-tools skill
- User asks about web research -> load google-search or parallel-research skill
"""


def _generate_skills() -> dict:
    """Generate all 10 SKILL.md files. Returns {name: content}."""
    skills = {}

    skills["apollo-enrichment"] = """# Apollo.io Enrichment via GTM Engine

## Overview
Apollo provides people search, enrichment, email finding, and organization data.
All calls go through gtm_enrich with provider="apollo".
Base URL: https://api.apollo.io/api/v1 (handled by proxy)

## Endpoints

### POST /people/match -- Enrich a single person
Parameters:
- email (string) -- Email to match
- first_name (string) -- Optional, improves match
- last_name (string) -- Optional
- organization_name (string) -- Optional
- domain (string) -- Company domain
- linkedin_url (string) -- LinkedIn profile URL

Example:
  gtm_enrich(provider="apollo", endpoint="/people/match",
             data={"email": "jane@acme.com"})

Response shape:
  { "person": { "id": "...", "first_name": "...", "last_name": "...",
    "title": "...", "email": "...", "organization": { ... },
    "phone_numbers": [...], "linkedin_url": "..." } }

### POST /mixed_people/search -- Search for people
Parameters:
- person_titles (array) -- Job titles to match ["VP Sales", "CRO"]
- organization_domains (array) -- Company domains ["acme.com"]
- person_locations (array) -- Locations ["San Francisco"]
- organization_num_employees_ranges (array) -- ["51,200"]
- q_organization_keyword_tags (array) -- Industry keywords ["SaaS", "fintech"]
- page (int) -- Pagination [default: 1]
- per_page (int) -- Results per page [default: 25, max: 100]

### POST /organizations/enrich -- Enrich a company
Parameters:
- domain (string) -- Company domain

### POST /mixed_companies/search -- Search companies
Parameters:
- organization_domains (array)
- organization_locations (array)
- organization_num_employees_ranges (array)

## Error Handling
- 401: Key invalid or expired. Tell user to re-add via gtm add-key apollo
- 422: Invalid parameters. Check required fields.
- 429: Rate limited. Apollo allows ~300 req/min on standard plans.

## Cost: ~$0.03/enrichment
"""

    skills["rocketreach-enrichment"] = """# RocketReach Enrichment via GTM Engine

## Overview
RocketReach provides contact lookup, email finding, and people search.
All calls go through gtm_enrich with provider="rocketreach".
Base URL: https://api.rocketreach.co/v2/api (handled by proxy)

## Endpoints

### GET /lookupProfile -- Look up a person
Query params:
- email (string) -- Email to look up
- linkedin_url (string) -- LinkedIn URL
- name (string) -- Full name (combine with company for best results)
- current_employer (string) -- Company name

Example:
  gtm_enrich(provider="rocketreach", method="GET", endpoint="/lookupProfile",
             params={"email": "jane@acme.com"})

Response shape:
  { "id": 123, "status": "complete", "name": "Jane Smith",
    "current_title": "VP Sales", "current_employer": "Acme Corp",
    "emails": [{"email": "jane@acme.com", "smtp_valid": "valid"}],
    "phones": [{"number": "+1415...", "type": "professional"}],
    "linkedin_url": "...", "city": "San Francisco", "region": "California" }

### GET /search -- Search for people
Query params:
- name (string) -- Person name
- current_title (array) -- Job titles
- current_employer (string) -- Company name
- company_domain (string) -- Company domain
- location (array) -- Locations
- start (int) -- Pagination offset [default: 1]
- page_size (int) -- Results per page [default: 10, max: 100]

### GET /lookupEmail -- Find email for a person
Query params:
- name (string) -- Full name
- current_employer (string) -- Company name

## Cost: ~$0.04/lookup
"""

    skills["google-search"] = """# Google Search via GTM Engine

## RapidAPI Google Search (provider: rapidapi_google)
Base URL: https://google-search74.p.rapidapi.com
Fast Google search results via RapidAPI.

### Search
  gtm_enrich(provider="rapidapi_google", method="GET", endpoint="/",
             params={"query": "acme corp SaaS funding", "limit": 10})

### Response Shape
  { "results": [
      { "title": "...", "url": "...", "description": "..." },
      ...
  ]}

## GTM Use Cases
- Company research: Search for funding announcements, news, press releases
- Competitive intelligence: Find competitor pricing, reviews, case studies
- Hiring signals: Search for job postings at target companies
- Technographic data: Search for tech stack mentions
- Event triggers: Recent news that makes outreach relevant
- Pre-call research: Latest news about a prospect's company

## Tips
- Use specific queries: "Acme Corp Series B funding 2024" not just "Acme Corp"
- Combine with Parallel AI for deeper research on the results
- Use for trigger-based outreach: find companies with recent events

## Cost: ~$0.001/search
"""

    skills["parallel-research"] = """# Parallel AI Web Research via GTM Engine

## Overview
Parallel AI provides AI-powered web research capabilities.
All calls go through gtm_enrich with provider="parallel".
Base URL: https://api.parallel.ai/v1 (handled by proxy)

## Use Cases for GTM
- Deep company research: Ask Parallel to research a company's products, culture, recent news
- Market analysis: Research a market segment or industry
- Competitive intelligence: Compare competitors
- Account planning: Build detailed profiles of target accounts
- Personalization research: Find talking points for outreach

## Example Workflows

### Research a Company
  gtm_enrich(provider="parallel", endpoint="/research",
             data={"query": "What does Acme Corp do? Recent funding, products, key people."})

### Find Talking Points for Outreach
  gtm_enrich(provider="parallel", endpoint="/research",
             data={"query": "Recent news about Stripe. Any new product launches or exec changes in the last 3 months?"})

## Tips
- Parallel works best for open-ended research questions
- Combine with Apollo/RocketReach for structured contact data
- Use for account research before outreach to personalize messaging

## Cost: ~$0.02/research query
"""

    skills["composio-connections"] = """# Composio Tool Connections

## Available Apps
| App ID | Name | Category | Use For |
|--------|------|----------|---------|
| slack | Slack | communication | Send messages, read channels |
| gmail | Gmail | communication | Send/read emails |
| google_sheets | Google Sheets | data | Read/write spreadsheets |
| google_docs | Google Docs | data | Create/edit documents |
| hubspot | HubSpot | crm | Manage contacts, deals |
| salesforce | Salesforce | crm | CRM data, leads |
| instantly | Instantly | sequencing | Email campaigns |
| lemlist | Lemlist | sequencing | Multi-channel outreach |
| linear | Linear | project | Issue tracking |
| notion | Notion | project | Databases, pages |

## Connecting an App
CLI: gtm connect slack
Dashboard: localhost:5555/tenant/{id}?tab=connections
The connection flow opens a browser for OAuth consent.

## After Connecting
Connected apps appear as additional MCP tools via Composio.
Example: After connecting Slack, you can send messages, read channels, etc.
After connecting Google Sheets, you can create/read/write spreadsheets.

## Entity Mapping
Each tenant gets entity_id = "gtm-{tenant_id}" in Composio.
This ensures connection isolation between tenants.

## Composio MCP Setup
After OAuth, the MCP URL is available. The `gtm setup-claude` command
automatically adds the Composio MCP server to .mcp.json if configured.
"""

    skills["waterfall-enrichment"] = """# Waterfall Enrichment Strategy

## Concept
Try multiple providers in sequence. Stop when you get the data you need.
Minimizes cost while maximizing coverage.
Check ~/.gtm/intelligence.json for YOUR specific hit rates to optimize the order.

## Recommended Waterfall Orders

### For Person Enrichment (by email):
1. Apollo /people/match -- Best for B2B, includes org data (~$0.03)
2. RocketReach /lookupProfile -- Strong contact data, phone numbers (~$0.04)
3. PDL /person/enrich -- Broadest coverage, likelihood scoring (~$0.05)

### For Email Finding (by domain + name):
1. RocketReach /lookupEmail -- Strong for finding specific people's emails
2. Apollo /people/match with domain + first_name + last_name
3. Hunter /email-finder with domain + first_name + last_name

### For Company Enrichment (by domain):
1. Apollo /organizations/enrich
2. PDL /company/enrich
3. Crustdata /screener/screen (for financial data)

### For Email Verification:
1. ZeroBounce /validate -- Most accurate (~$0.01)
2. Hunter /email-verifier -- Good backup

## Implementation Pattern
```python
providers = ["apollo", "rocketreach", "pdl"]
for provider in providers:
    result = gtm_enrich(provider=provider, ...)
    if result["status_code"] == 200 and has_useful_data(result["data"]):
        break  # Got data, stop trying
```

## Cost Optimization
- Always start with cheapest provider if quality is similar
- Track hit rates in intelligence.json to optimize over time
- Verify emails before sending campaigns (ZeroBounce or Hunter)
"""

    skills["gtm-workflows"] = """# Common GTM Workflows

## Workflow 1: Prospect Research
1. User provides target criteria (industry, company size, titles)
2. Search Apollo /mixed_people/search with criteria
3. Enrich top results via waterfall (Apollo -> RocketReach)
4. Score against ICP
5. Export to Google Sheets (via Composio connection)

## Workflow 2: Account-Based Enrichment
1. User provides list of target domains
2. For each domain: Apollo /organizations/enrich
3. Find key contacts: Apollo /mixed_people/search per domain
4. Find/verify emails: RocketReach or Hunter
5. Push to CRM via HubSpot/Salesforce connection

## Workflow 3: Email Campaign Launch
1. Build prospect list (Workflow 1 or 2)
2. Verify all emails via ZeroBounce
3. Push to Instantly via /lead/add
4. Create campaign via /campaign/create
5. Monitor via Instantly dashboard or API

## Workflow 4: Company Research
1. Use Parallel AI for deep company research
2. Use Google Search for recent news/funding
3. Enrich company via Apollo/Crustdata
4. Find contacts at company
5. Build personalized outreach angles

## Workflow 5: Competitive Intelligence
1. Search Google for competitor info (rapidapi_google)
2. Deep research with Parallel AI
3. Find their customers via case studies
4. Build lookalike prospect list via Apollo search

## Human-in-the-Loop Checkpoints
- Before sending any campaign: require approval
- Before adding >100 leads: confirm with user
- Before spending >$10 on enrichment: confirm budget
"""

    skills["list-building"] = """# Prospect List Building

## Step 1: Define ICP Criteria
Gather from user:
- Target titles (VP Sales, CRO, Head of Growth)
- Company size (51-200, 201-1000)
- Industries (SaaS, FinTech)
- Locations (US, SF Bay Area)
- Technologies used (optional)

## Step 2: Search for Prospects
Apollo /mixed_people/search:
  data={"person_titles": ["VP Sales", "CRO"],
        "organization_num_employees_ranges": ["51,200"],
        "person_locations": ["United States"],
        "per_page": 100, "page": 1}

Or RocketReach /search:
  params={"current_title": ["VP Sales"],
          "company_size": "51-200",
          "location": ["United States"]}

## Step 3: Enrich Each Prospect
For each result, enrich with additional data:
- Phone numbers (RocketReach /lookupProfile)
- Email verification (ZeroBounce /validate)
- Company data (Apollo /organizations/enrich)

## Step 4: Score Against ICP
Score each prospect 0-100 based on:
- Title match (40 points)
- Company size match (20 points)
- Industry match (20 points)
- Location match (10 points)
- Data completeness (10 points)

## Step 5: Export
- Google Sheets (via Composio connection)
- CSV (direct output)
- HubSpot/Salesforce (via Composio connection)
- Instantly (for email campaigns)

## Cost Awareness
Show the user: "Building a list of N people will cost approximately $X.XX"
Track actual cost and report: "List complete: N people for $X.XX (Y% hit rate)"
"""

    skills["instantly-campaigns"] = """# Instantly Email Campaigns

Base URL: https://api.instantly.ai/api/v1 (via proxy)
Auth: query param api_key (handled automatically)

## Endpoints

### GET /campaign/list -- List campaigns
  gtm_enrich(provider="instantly", method="GET", endpoint="/campaign/list")

### POST /campaign/create -- Create a new campaign
  data={"name": "Q1 Outreach", "schedule": {...}}

### POST /lead/add -- Add leads to a campaign
  data={"campaign_id": "...",
        "leads": [{"email": "...", "first_name": "...",
                    "last_name": "...", "company_name": "..."}]}

### GET /analytics/campaign/summary -- Campaign metrics
  params={"campaign_id": "..."}

### POST /lead/delete -- Remove leads
  data={"campaign_id": "...", "delete_list": ["email1@...", "email2@..."]}

## Campaign Workflow
1. Create campaign with name and schedule
2. Add verified leads (always verify first!)
3. Set sequences/steps in Instantly UI or via API
4. Monitor analytics via /analytics/campaign/summary

## Important: Always verify emails before adding to Instantly
Sending to invalid emails damages sender reputation.
"""

    skills["scraping-tools"] = """# Web Scraping Tools: Apify + Firecrawl

## Firecrawl (Recommended for simple scraping)
Base URL: https://api.firecrawl.dev/v1

### POST /scrape -- Scrape a single URL
  gtm_enrich(provider="firecrawl", endpoint="/scrape",
             data={"url": "https://example.com/about",
                   "formats": ["markdown"]})

### POST /crawl -- Crawl an entire site
  data={"url": "https://example.com",
        "limit": 50,
        "scrapeOptions": {"formats": ["markdown"]}}
Returns a job ID. Poll GET /crawl/{id} for status.

### POST /map -- Get sitemap of a domain
  data={"url": "https://example.com"}

## Apify (For complex scraping with actors)
Base URL: https://api.apify.com/v2

### POST /acts/{actorId}/runs -- Run a scraping actor
  gtm_enrich(provider="apify", endpoint="/acts/{actorId}/runs",
             data={"startUrls": [{"url": "..."}]})

Popular actors:
- apify/web-scraper -- General web scraping
- apify/google-search-scraper -- Google SERP scraping
- apify/instagram-scraper -- Instagram profiles

## Use Cases for GTM
- Scrape competitor pricing pages
- Extract testimonials/case studies
- Build company lists from directories
- Monitor job postings (hiring signals)
"""

    return skills


def _generate_rules() -> dict:
    """Generate rule files. Returns {filename: content}."""
    rules = {}

    rules["security.md"] = """# Security Rules for GTM Engine Development

When working with vault/ files:
- Never log or print API key values
- Never return key values from any function
- Always use fingerprints for identification
- The proxy pattern is mandatory: keys go IN but never come OUT
- Test that no key material appears in any return value

When handling user-provided keys:
- Store immediately via gtm_add_key, do not hold in variables
- Remind users that keys shown in chat context should be rotated
- Never include keys in commit messages or comments

When modifying .vault/ code:
- Run the full security test suite: python3 tests/test_vault_security.py
- Run multi-tenant tests: python3 tests/test_multi_tenant.py
"""

    rules["enrichment.md"] = """# Enrichment Rules

When making enrichment calls:
- Always check provider availability first (gtm_vault_status)
- Handle rate limiting gracefully (429 responses)
- Log the provider and endpoint, never the key
- Return data to user, never auth headers
- Always show cost estimates before batch operations (>10 records)
- Track results in intelligence.json via the proxy

When building waterfall enrichment:
- Check intelligence.json for provider hit rates before choosing order
- Try cheapest provider first when quality is comparable
- Stop as soon as sufficient data is obtained
- Track which provider returned data for performance analytics
- Report total cost and hit rate after completion
"""

    return rules
