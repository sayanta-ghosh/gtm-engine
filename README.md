# GTM Engine by nRev

AI-native go-to-market toolkit. Makes Claude Code your GTM co-pilot with secure API key management, multi-provider enrichment, and compound intelligence.

## Quick Start

```bash
pip3 install git+https://github.com/nrev-ai/gtm-engine.git
gtm init
export GTM_PASSPHRASE="your-passphrase"
gtm setup-claude
# Restart Claude Code — done.
```

## What It Does

**GTM Engine** turns Claude Code into a GTM powerhouse:

1. **Persistent Intelligence** — Remembers which providers work best for YOUR ICP across sessions. After 30 days: *"Your best waterfall is Apollo → RocketReach (89% hit rate, $0.05/contact)."*

2. **Cost Transparency** — Shows estimates before every call, receipts after. *"This will cost ~$3. Done: 50 contacts for $2.87 (92% hit rate)."*

3. **Secure Key Vault** — API keys are encrypted (AES-256, PBKDF2 600K) and never appear in conversation. Claude only sees fingerprints.

## Commands

| Command | What It Does |
|---------|-------------|
| `gtm init` | Discovery-first onboarding: understands your GTM goals, recommends workflows |
| `gtm add-key <provider>` | Store a BYOK API key (encrypted, never retrievable) |
| `gtm status` | Vault health + intelligence stats (hit rates, costs, best waterfalls) |
| `gtm enrich -p <provider>` | Enrichment with cost estimate + receipt |
| `gtm dashboard` | Launch web UI at localhost:5555 |
| `gtm connect <app>` | OAuth connect tools (Slack, Sheets, HubSpot, etc.) |
| `gtm setup-claude` | Auto-configure Claude Code (MCP server, skills, rules) |

## Supported Providers

| Provider | What It Does |
|----------|-------------|
| Apollo | People search, enrichment, org data |
| RocketReach | Contact info, email/phone finding |
| RapidAPI Google | Google search for company research |
| Parallel AI | AI-powered web research |
| PDL | Person + company enrichment |
| Hunter | Email finding + verification |
| ZeroBounce | Email validation |
| Apify | Web scraping actors |
| Firecrawl | Web crawling + scraping |
| Instantly | Email sequences |
| Crustdata | Company data enrichment |
| Composio | OAuth tool connections |
| LeadMagic | B2B data enrichment |

## Architecture

```
vault/       → Encrypted multi-tenant API key vault
cli/         → Click-based CLI (gtm command)
dashboard/   → FastAPI web UI
.vault/      → Encrypted key storage (never commit)
```

## Security

- API keys are encrypted with AES-256 + PBKDF2 (600K iterations)
- Keys never appear in Claude Code conversation context
- Proxy pattern: keys go IN but never come OUT
- Only fingerprints are ever returned
- `.vault/` and `.env` are gitignored

## License

Proprietary — nRev, Inc.
