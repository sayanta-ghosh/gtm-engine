# nrv Quickstart — Tester Guide

## Prerequisites

- Python 3.10+
- Docker (for PostgreSQL + Redis)
- Google Chrome (for OAuth login)

## 1. Setup (one-time)

```bash
# Clone the repo
git clone https://github.com/sayanta-ghosh/nrv.git
cd nrv

# Start infrastructure
docker compose up -d postgres redis

# Install the CLI
pip3 install -e .

# Verify installation
nrv --version
nrv --help
```

## 2. Start the server

```bash
# Copy the env file (ask Sayanta for the .env file)
# It contains JWT_SECRET_KEY, Google OAuth, and platform API keys

# Run the server
python3 -m uvicorn server.app:app --host 0.0.0.0 --port 8000 --reload

# Verify (in another terminal)
curl http://localhost:8000/health
# Should return: {"status":"ok","version":"0.1.0"}
```

## 3. Create your account

```bash
# This opens your browser for Google OAuth
# It creates a new tenant with 200 free credits
nrv auth login

# Check your account
nrv status
```

You should see:
```
╭────────────── nrv status ──────────────╮
│ Email:   you@company.com               │
│ Tenant:  company-a1b2c3d4              │
│ Token:   valid                         │
│ Server:  http://localhost:8000 (online) │
│ Credits: 200                           │
│ ...                                    │
╰────────────────────────────────────────╯
```

## 4. Add your own API keys (optional, saves credits)

```bash
# Platform keys are pre-configured for Apollo, RocketReach, PredictLeads
# BYOK keys make calls FREE (no credits charged)

nrv keys add apollo        # Paste your Apollo API key
nrv keys add rocketreach   # Paste your RocketReach API key
nrv keys list              # Verify
```

## 5. Try the workflows

### Search for people

```bash
# By title + company
nrv search people --title "VP Sales" --company "Google" --limit 10

# By title + domain
nrv search people --title "CTO,VP Engineering" --domain stripe.com

# By school (alumni search — auto-uses RocketReach)
nrv search people --school "IIT Kharagpur" --title "Director,VP,Head"

# By past company (alumni search)
nrv search people --past-company "Mindtickle" --title "VP Sales,Head of Growth"

# With explicit provider
nrv search people --title "CRO" --provider rocketreach --limit 20

# Raw JSON output
nrv search people --title "CMO" --company "Salesforce" --json-output
```

### Search for companies

```bash
nrv search companies --name "Stripe"
nrv search companies --industry "SaaS" --size "50-200"
```

### Enrich a person

```bash
# By email
nrv enrich person --email john@stripe.com

# By name + company
nrv enrich person --name "John Doe" --domain stripe.com

# By LinkedIn URL
nrv enrich person --linkedin https://linkedin.com/in/johndoe

# With phone + personal email
nrv enrich person --email john@acme.com --reveal-phone --reveal-emails

# Dry run (shows what would be sent)
nrv enrich person --email test@example.com --dry-run
```

### Enrich a company

```bash
nrv enrich company --domain stripe.com
nrv enrich company --domain https://www.salesforce.com  # auto-cleaned
```

### Batch enrichment

```bash
# Create a CSV file: emails.csv
# email,first_name,last_name,domain
# john@acme.com,John,Doe,acme.com
# jane@stripe.com,Jane,Smith,stripe.com

nrv enrich batch --file emails.csv
nrv enrich batch --file emails.csv --dry-run  # preview first
```

### Check credits

```bash
nrv credits balance
nrv credits history --limit 10
```

## 6. Use with Claude Code (optional)

```bash
# Install Claude Code skills + CLAUDE.md
nrv setup-claude

# Then in Claude Code, you can say:
# "Find VP Sales at fintech companies in California"
# "Enrich john@stripe.com"
# "Show my credit balance"
```

## Architecture Notes

- **All API calls go through the server** — the CLI never calls Apollo/RocketReach directly
- **Platform keys** (pre-configured) cost credits; **BYOK keys** are free
- **Every new account gets 200 credits** on signup
- **Enrichment**: ~1 credit per person, ~1 per company
- **Search**: ~1 credit per 25 results
- **Cache**: Results are cached (7 days for enrichment, 1 hour for search) — no re-charge

## Available Providers

| Provider | Operations | Best For |
|----------|-----------|----------|
| Apollo | enrich person, enrich company, search people, search companies, bulk enrich | General enrichment + search |
| RocketReach | enrich person, search people, enrich company, search companies | School/alumni searches, past company |
| PredictLeads | company jobs, company news, similar companies, + more | Company intelligence |

## Troubleshooting

**"Not logged in"**: Run `nrv auth login`

**"Could not connect to server"**: Make sure the server is running on port 8000

**"Session expired"**: Run `nrv auth login` again (tokens last 24 hours)

**Search returns 0 results**: Try broader title filters, or check the provider. Apollo and RocketReach have different data coverage.

**Credits running low**: Check with `nrv credits balance`. Add BYOK keys to get free calls.
