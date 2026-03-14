"""
gtm init — Discovery-first onboarding wizard

Philosophy: understand the user's GTM goals FIRST, then recommend
the right workflows and providers. Keys come last — only for what
they actually need.

Flow:
1. Company basics (name, domain)
2. GTM stage & goals (what are you trying to do?)
3. ICP definition (who are you selling to?)
4. Challenges (what's blocking you?)
5. Workflow recommendations (based on 1-4)
6. Set up vault (passphrase, tenant)
7. Add keys only for recommended providers
"""

import uuid
import json
import click
from pathlib import Path

from ..config import save_config, load_config, ensure_gtm_dir
from ..output import console, print_success, print_error, print_info, print_header


# ── GTM Workflow Catalog ──────────────────────────────────────────
# Each workflow maps goals → providers needed → what it delivers

WORKFLOWS = {
    "prospect_research": {
        "name": "Prospect Research",
        "desc": "Find and enrich ideal prospects matching your ICP",
        "providers": ["apollo", "rocketreach"],
        "optional": ["rapidapi_google", "parallel"],
        "triggers": ["find leads", "prospect", "research", "icp"],
    },
    "account_intelligence": {
        "name": "Account Intelligence",
        "desc": "Deep research on target accounts — news, funding, tech stack, org structure",
        "providers": ["rapidapi_google", "parallel"],
        "optional": ["apollo"],
        "triggers": ["research", "account", "company", "intel"],
    },
    "email_outreach": {
        "name": "Email Campaign Launch",
        "desc": "Build lists, verify emails, launch sequences via Instantly",
        "providers": ["apollo", "rocketreach"],
        "optional": ["instantly"],
        "triggers": ["email", "outreach", "campaign", "sequence", "cold email"],
    },
    "enrichment_waterfall": {
        "name": "Data Enrichment Waterfall",
        "desc": "Enrich a list of contacts/companies through multiple providers for max coverage",
        "providers": ["apollo"],
        "optional": ["rocketreach"],
        "triggers": ["enrich", "data", "waterfall", "contacts", "csv"],
    },
    "competitive_intel": {
        "name": "Competitive Intelligence",
        "desc": "Research competitors, find their customers, build lookalike prospect lists",
        "providers": ["rapidapi_google", "parallel"],
        "optional": ["apollo"],
        "triggers": ["competitor", "competitive", "market", "landscape"],
    },
    "website_scraping": {
        "name": "Web Scraping & Data Collection",
        "desc": "Scrape websites, directories, and job boards for GTM signals",
        "providers": ["apify", "firecrawl"],
        "optional": ["rapidapi_google"],
        "triggers": ["scrape", "crawl", "website", "extract"],
    },
}

# ICP templates for common segments
ICP_TEMPLATES = {
    "smb_saas": {
        "label": "SMB SaaS",
        "company_size": "10-100",
        "typical_titles": ["Founder", "CEO", "Head of Growth", "VP Sales"],
        "industries": ["SaaS", "Software", "Technology"],
    },
    "mid_market": {
        "label": "Mid-Market",
        "company_size": "100-1000",
        "typical_titles": ["VP Sales", "CRO", "Director of Marketing", "CMO"],
        "industries": ["Varies"],
    },
    "enterprise": {
        "label": "Enterprise",
        "company_size": "1000+",
        "typical_titles": ["SVP", "VP", "Director", "Head of"],
        "industries": ["Varies"],
    },
    "agencies": {
        "label": "Agencies & Consultancies",
        "company_size": "10-200",
        "typical_titles": ["Managing Director", "Partner", "Head of Strategy"],
        "industries": ["Marketing", "Consulting", "Creative"],
    },
}


def _find_project_root() -> Path:
    """Find gtm-engine project root by looking for vault/ directory."""
    candidates = [
        Path.cwd(),
        Path.cwd().parent,
        Path(__file__).resolve().parent.parent.parent,
    ]
    for p in candidates:
        if (p / "vault" / "proxy.py").exists():
            return p
    return Path(__file__).resolve().parent.parent.parent


def _recommend_workflows(goals, challenges) -> list:
    """Based on goals and challenges, recommend the best workflows."""
    goals_lower = " ".join(goals).lower() if goals else ""
    challenges_lower = " ".join(challenges).lower() if challenges else ""
    combined = goals_lower + " " + challenges_lower

    scored = []
    for wf_id, wf in WORKFLOWS.items():
        score = 0
        for trigger in wf["triggers"]:
            if trigger in combined:
                score += 10
        # Everyone needs prospect research
        if wf_id == "prospect_research":
            score += 5
        if score > 0:
            scored.append((score, wf_id, wf))

    # Sort by score descending, return top 3
    scored.sort(key=lambda x: -x[0])
    if not scored:
        # Default recommendations
        return [
            ("prospect_research", WORKFLOWS["prospect_research"]),
            ("account_intelligence", WORKFLOWS["account_intelligence"]),
        ]
    return [(wf_id, wf) for _, wf_id, wf in scored[:3]]


def _get_all_needed_providers(recommended_workflows) -> tuple:
    """From recommended workflows, extract required and optional providers."""
    required = set()
    optional = set()
    for wf_id, wf in recommended_workflows:
        for p in wf["providers"]:
            required.add(p)
        for p in wf.get("optional", []):
            optional.add(p)
    optional -= required  # Don't list something as both
    return sorted(required), sorted(optional)


@click.command()
@click.option("--name", default=None, help="Your name or company")
@click.option("--domain", default=None, help="Your company domain (e.g., acme.com)")
@click.option(
    "--passphrase",
    default=None,
    help="Vault passphrase (prompted securely if omitted)",
)
@click.option("--tenant-id", default=None, help="Custom tenant ID (auto-generated if omitted)")
@click.option("--non-interactive", is_flag=True, help="Skip discovery, just create tenant")
@click.option("--quick", is_flag=True, help="Quick setup — skip discovery, just tenant + key")
def init_cmd(name, domain, passphrase, tenant_id, non_interactive, quick):
    """Onboard: discover your GTM goals, set up your vault, get started.

    The wizard first understands your business and goals, then recommends
    the best GTM workflows and which API providers you need.
    """
    import sys

    console.print()
    print_header("GTM Engine", "AI-native go-to-market toolkit by nRev")
    console.print()

    # ── Quick or Non-Interactive: minimal setup ────────────────────
    if non_interactive or quick:
        if not name:
            name = click.prompt("  Company name")
        if not passphrase:
            passphrase = click.prompt("  Vault passphrase", hide_input=True,
                                       confirmation_prompt=True)
        _create_tenant(name, passphrase, tenant_id)
        if quick:
            _offer_key_add(name, passphrase, tenant_id=None)
        return

    # ── Phase 1: Discovery ────────────────────────────────────────
    console.print("  [bold cyan]Let's get to know your GTM motion.[/bold cyan]")
    console.print("  [dim]This helps us recommend the right workflows and tools.[/dim]")
    console.print()

    # Company basics
    if not name:
        name = click.prompt("  Your company name")
    if not domain:
        domain = click.prompt("  Your company domain (e.g., acme.com)", default="", show_default=False)
    console.print()

    # GTM stage
    console.print("  [bold]What stage is your GTM motion?[/bold]")
    console.print("    1. Just getting started — need to find my first customers")
    console.print("    2. Growing — have product-market fit, need more pipeline")
    console.print("    3. Scaling — need to automate and optimize outbound")
    console.print("    4. Enterprise — complex sales, ABM, multi-channel")
    console.print()
    stage = click.prompt("  Stage (1-4)", type=int, default=2)
    console.print()

    # Goals — multi-select
    console.print("  [bold]What are your top GTM goals? (select all that apply)[/bold]")
    goal_options = [
        "Find and research ideal prospects",
        "Enrich a list of contacts with email/phone",
        "Launch email outreach campaigns",
        "Research target accounts deeply",
        "Monitor competitors",
        "Scrape websites for GTM data",
    ]
    for i, g in enumerate(goal_options, 1):
        console.print(f"    {i}. {g}")
    console.print()
    goals_input = click.prompt(
        "  Goals (comma-separated numbers, e.g., 1,2,3)",
        default="1,2",
    )
    selected_goals = []
    for g in goals_input.split(","):
        g = g.strip()
        try:
            idx = int(g) - 1
            if 0 <= idx < len(goal_options):
                selected_goals.append(goal_options[idx])
        except ValueError:
            selected_goals.append(g)
    console.print()

    # ICP
    console.print("  [bold]Who's your Ideal Customer Profile (ICP)?[/bold]")
    console.print("    1. SMB SaaS (10-100 employees)")
    console.print("    2. Mid-Market (100-1,000 employees)")
    console.print("    3. Enterprise (1,000+ employees)")
    console.print("    4. Agencies & Consultancies")
    console.print("    5. Custom — I'll describe it")
    console.print()
    icp_choice = click.prompt("  ICP (1-5)", type=int, default=2)
    icp_templates_list = list(ICP_TEMPLATES.keys())
    icp_data = {}
    if 1 <= icp_choice <= 4:
        icp_key = icp_templates_list[icp_choice - 1]
        icp_data = ICP_TEMPLATES[icp_key]
        console.print(f"  → {icp_data['label']}: typical titles are {', '.join(icp_data['typical_titles'])}")
    else:
        custom_icp = click.prompt("  Describe your ICP in a sentence")
        icp_data = {"label": "Custom", "description": custom_icp}
    console.print()

    # Titles they sell to
    console.print("  [bold]What titles do you typically sell to?[/bold]")
    if icp_data.get("typical_titles"):
        default_titles = ", ".join(icp_data["typical_titles"][:3])
        titles_input = click.prompt("  Target titles", default=default_titles)
    else:
        titles_input = click.prompt("  Target titles (e.g., VP Sales, CRO, Head of Growth)")
    target_titles = [t.strip() for t in titles_input.split(",")]
    console.print()

    # Challenges
    console.print("  [bold]What's your biggest GTM challenge right now?[/bold]")
    console.print("    1. Not enough qualified leads")
    console.print("    2. Low email response rates")
    console.print("    3. Spending too much time on manual research")
    console.print("    4. Bad data quality / bounce rates")
    console.print("    5. Don't know which tools to use")
    console.print()
    challenge_input = click.prompt("  Challenge (number or describe)", default="1")
    challenges_map = {
        "1": "find leads prospect research",
        "2": "email outreach campaign sequence",
        "3": "research account intel automation",
        "4": "enrich data waterfall verify",
        "5": "prospect research email outreach",
    }
    challenges = [challenges_map.get(challenge_input.strip(), challenge_input)]
    console.print()

    # ── Phase 2: Recommendations ──────────────────────────────────
    recommended = _recommend_workflows(selected_goals, challenges)
    required_providers, optional_providers = _get_all_needed_providers(recommended)

    console.print("  " + "─" * 56)
    console.print()
    console.print("  [bold green]Here's what I recommend for your GTM motion:[/bold green]")
    console.print()

    for wf_id, wf in recommended:
        providers_str = " + ".join(wf["providers"])
        console.print(f"  [bold]→ {wf['name']}[/bold]")
        console.print(f"    {wf['desc']}")
        console.print(f"    [dim]Uses: {providers_str}[/dim]")
        console.print()

    console.print(f"  [bold]API keys you'll need:[/bold]")
    for p in required_providers:
        console.print(f"    [green]●[/green] {p} [dim](required)[/dim]")
    for p in optional_providers:
        console.print(f"    [yellow]○[/yellow] {p} [dim](optional, adds more coverage)[/dim]")
    console.print()

    if not click.confirm("  Ready to set up your vault?", default=True):
        console.print("\n  No problem. Run [bold]gtm init[/bold] when you're ready.\n")
        return

    # ── Phase 3: Vault Setup ──────────────────────────────────────
    console.print()
    if not passphrase:
        passphrase = click.prompt("  Create a vault passphrase (encrypts your keys)",
                                   hide_input=True, confirmation_prompt=True)

    actual_tenant_id = _create_tenant(name, passphrase, tenant_id)
    if not actual_tenant_id:
        return

    # Save ICP profile and recommendations alongside config
    config = load_config()
    config["onboarding"] = {
        "company_name": name,
        "company_domain": domain or "",
        "stage": stage,
        "goals": selected_goals,
        "icp": icp_data,
        "target_titles": target_titles,
        "challenges": challenges,
        "recommended_workflows": [wf_id for wf_id, _ in recommended],
        "required_providers": required_providers,
    }
    save_config(config)

    # ── Phase 4: Add Keys (only for recommended providers) ────────
    console.print()
    console.print("  [bold cyan]Now let's add your API keys.[/bold cyan]")
    console.print("  [dim]Keys are encrypted immediately (AES-256) and never stored in plain text.[/dim]")
    console.print("  [dim]You can skip any and add later with: gtm add-key <provider>[/dim]")
    console.print()

    _offer_recommended_keys(actual_tenant_id, passphrase, required_providers, optional_providers)

    # ── Phase 5: Next Steps ───────────────────────────────────────
    console.print()
    console.print("  " + "─" * 56)
    console.print()
    console.print("  [bold green]You're all set! Here's what to do next:[/bold green]")
    console.print()
    console.print("    1. Set your passphrase as an env var:")
    console.print('       [dim]export GTM_PASSPHRASE="your-passphrase"[/dim]')
    console.print()
    console.print("    2. Configure Claude Code:")
    console.print("       [dim]gtm setup-claude[/dim]")
    console.print()
    console.print("    3. Open Claude Code and try:")
    if "prospect_research" in [wf_id for wf_id, _ in recommended]:
        console.print(f'       [dim]"Find {target_titles[0]}s at {icp_data.get("label", "mid-market")} companies"[/dim]')
    elif "account_intelligence" in [wf_id for wf_id, _ in recommended]:
        console.print(f'       [dim]"Research {domain or "target company"} — recent news, funding, key people"[/dim]')
    else:
        console.print('       [dim]"Show my GTM engine status"[/dim]')
    console.print()


def _create_tenant(name, passphrase, tenant_id=None) -> str:
    """Create the vault tenant. Returns actual_tenant_id or None on failure."""
    import sys

    project_root = _find_project_root()
    vault_base = project_root / ".vault"

    if not tenant_id:
        slug = name.lower().replace(" ", "-")[:20]
        short_id = str(uuid.uuid4())[:8]
        tenant_id = f"{slug}-{short_id}"

    console.print(f"  Creating tenant vault for [bold]{name}[/bold]...")
    console.print()

    try:
        sys.path.insert(0, str(project_root))
        from vault.tenant import TenantVault
        from vault.key_manager import KeyManager

        tv = TenantVault(base_path=vault_base)
        km = KeyManager(tv)

        result = km.onboard_tenant(name, passphrase, tenant_id)

        if not result.get("success"):
            print_error(f"Failed: {result.get('error', 'Unknown error')}")
            return None

        actual_tenant_id = result["tenant_id"]
        print_success(f"Tenant created: [bold]{actual_tenant_id}[/bold]")
        print_info(f"Vault: {vault_base}")

        config = load_config()
        config.update({
            "tenant_id": actual_tenant_id,
            "tenant_name": name,
            "vault_base": str(vault_base),
            "project_root": str(project_root),
            "dashboard_port": 5555,
        })
        save_config(config)
        print_success("Config saved to ~/.gtm/config.json")

        return actual_tenant_id

    except ImportError as e:
        print_error(f"Cannot import vault modules: {e}")
        print_info("Make sure you're in the gtm-engine directory or it's installed.")
        return None
    except Exception as e:
        print_error(f"Error: {e}")
        return None


def _offer_recommended_keys(tenant_id, passphrase, required, optional):
    """Prompt the user to add keys for recommended providers."""
    import sys

    project_root = _find_project_root()
    sys.path.insert(0, str(project_root))
    from vault.tenant import TenantVault
    from vault.key_manager import KeyManager

    vault_base = project_root / ".vault"
    tv = TenantVault(base_path=vault_base)
    km = KeyManager(tv)
    tv.unlock_tenant(tenant_id, passphrase)

    provider_hints = {
        "apollo": "Get yours at app.apollo.io → Settings → API Keys",
        "rocketreach": "Get yours at rocketreach.co → Account → API",
        "rapidapi_google": "Get yours at rapidapi.com → Subscribe to Google Search",
        "parallel": "Get yours at parallel.ai → API Settings",
        "apify": "Get yours at console.apify.com → Settings → Integrations",
        "firecrawl": "Get yours at firecrawl.dev → Dashboard → API Keys",
        "instantly": "Get yours at instantly.ai → Settings → API",
    }

    for provider in required + optional:
        is_optional = provider in optional
        label = "[dim](optional)[/dim]" if is_optional else "[dim](required)[/dim]"
        hint = provider_hints.get(provider, "")

        console.print(f"  [bold]{provider}[/bold] {label}")
        if hint:
            console.print(f"    [dim]{hint}[/dim]")

        if click.confirm(f"  Add {provider} key now?", default=not is_optional):
            key_value = click.prompt(f"  Paste your {provider} key (hidden)", hide_input=True)
            if key_value.strip():
                try:
                    add_result = km.add_key(tenant_id, provider, key_value.strip())
                    if add_result.get("success"):
                        print_success(
                            f"  Stored {provider} "
                            f"(fingerprint: {add_result.get('fingerprint', '?')[:12]})"
                        )
                    else:
                        print_error(f"  Failed: {add_result.get('error')}")
                except Exception as e:
                    print_error(f"  Error storing key: {e}")
            else:
                print_info("  Skipped (empty key)")
        else:
            print_info(f"  Skipped — add later with: gtm add-key {provider}")
        console.print()


def _offer_key_add(name, passphrase, tenant_id=None):
    """Simple key add (for --quick mode)."""
    from vault.proxy import PROVIDER_AUTH_CONFIG

    console.print()
    if click.confirm("  Add your first API key?", default=True):
        console.print()
        console.print("  Available providers:")
        providers = list(PROVIDER_AUTH_CONFIG.keys())
        for i, p in enumerate(providers, 1):
            console.print(f"    {i:2d}. {p}")
        console.print()
        provider = click.prompt("  Provider (name or number)", type=str).strip()

        try:
            idx = int(provider) - 1
            if 0 <= idx < len(providers):
                provider = providers[idx]
        except ValueError:
            pass

        provider = provider.lower()
        if provider in PROVIDER_AUTH_CONFIG:
            key_value = click.prompt(
                f"  Paste your {provider} API key (hidden)",
                hide_input=True,
            )
            if key_value.strip():
                import sys
                project_root = _find_project_root()
                sys.path.insert(0, str(project_root))
                from vault.tenant import TenantVault
                from vault.key_manager import KeyManager

                config = load_config()
                actual_tenant_id = config.get("tenant_id", tenant_id)
                vault_base = project_root / ".vault"
                tv = TenantVault(base_path=vault_base)
                km = KeyManager(tv)
                tv.unlock_tenant(actual_tenant_id, passphrase)
                add_result = km.add_key(actual_tenant_id, provider, key_value.strip())
                if add_result.get("success"):
                    print_success(
                        f"Stored {provider} key "
                        f"(fingerprint: {add_result.get('fingerprint', '?')[:12]})"
                    )
                else:
                    print_error(f"Failed to store key: {add_result.get('error')}")
        else:
            print_error(f"Unknown provider: {provider}")
