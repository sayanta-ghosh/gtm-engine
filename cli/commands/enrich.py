"""
gtm enrich — Make enrichment calls with cost estimates and receipts

The key differentiator: shows estimated cost BEFORE running,
tracks costs/hit-rates, and provides a receipt AFTER.
"""

import sys
import json
import time
import click
from pathlib import Path

from ..config import load_config, resolve_passphrase, track_enrichment
from ..output import (
    console, print_success, print_error, print_info,
    cost_estimate, enrichment_receipt,
)


# Estimated cost per record (cents) by provider
# These are rough averages — users can override
COST_ESTIMATES = {
    "apollo": 3.0,       # ~$0.03/enrichment
    "rocketreach": 4.0,  # ~$0.04/enrichment
    "pdl": 5.0,          # ~$0.05/enrichment
    "hunter": 1.5,       # ~$0.015/request
    "leadmagic": 3.0,
    "zerobounce": 1.0,   # ~$0.01/verification
    "apify": 5.0,
    "firecrawl": 2.0,
    "instantly": 0.0,    # Usage-based via their plan
    "crustdata": 5.0,
    "parallel": 2.0,
    "rapidapi_google": 0.1,
    "composio": 0.0,
}

# Smart endpoint mapping: high-level flags -> provider-specific endpoints
ENDPOINT_MAP = {
    "apollo": {
        "email": ("POST", "/people/match", lambda e: {"email": e}),
        "domain": ("POST", "/mixed_companies/search", lambda d: {"organization_domains": [d]}),
        "linkedin": ("POST", "/people/match", lambda u: {"linkedin_url": u}),
        "company": ("POST", "/organizations/enrich", lambda c: {"domain": c}),
    },
    "rocketreach": {
        "email": ("GET", "/lookupProfile", lambda e: {"email": e}),
        "domain": ("GET", "/search", lambda d: {"company_domain": d}),
        "linkedin": ("GET", "/lookupProfile", lambda u: {"linkedin_url": u}),
    },
    "hunter": {
        "email": ("GET", "/email-verifier", lambda e: {"email": e}),
        "domain": ("GET", "/domain-search", lambda d: {"domain": d}),
    },
    "pdl": {
        "email": ("GET", "/person/enrich", lambda e: {"email": e}),
        "domain": ("GET", "/company/enrich", lambda d: {"website": d}),
        "linkedin": ("GET", "/person/enrich", lambda u: {"profile": u}),
    },
    "zerobounce": {
        "email": ("GET", "/validate", lambda e: {"email": e}),
    },
}


@click.command()
@click.option("--provider", "-p", required=True, help="Provider (apollo, rocketreach, etc.)")
@click.option("--email", default=None, help="Email to enrich")
@click.option("--domain", default=None, help="Domain to search")
@click.option("--linkedin", default=None, help="LinkedIn URL to enrich")
@click.option("--company", default=None, help="Company name/domain to enrich")
@click.option("--endpoint", default=None, help="Custom endpoint path (advanced)")
@click.option("--method", default=None, help="HTTP method [default: POST]")
@click.option("--data", "data_str", default=None, help="JSON body as string (advanced)")
@click.option("--params", "params_str", default=None, help="Query params as JSON string")
@click.option("--json-output", "as_json", is_flag=True, help="Raw JSON output")
@click.option("--passphrase", default=None, help="Vault passphrase")
def enrich(provider, email, domain, linkedin, company, endpoint, method,
           data_str, params_str, as_json, passphrase):
    """Make an authenticated enrichment call via the secure proxy.

    The API key is injected automatically and never visible.

    Examples:
        gtm enrich -p apollo --email jane@acme.com
        gtm enrich -p rocketreach --domain stripe.com
        gtm enrich -p hunter --email test@example.com
        gtm enrich -p apollo --endpoint /mixed_people/search --data '{"person_titles":["VP Sales"]}'
    """
    config = load_config()
    tenant_id = config.get("tenant_id")
    vault_base = config.get("vault_base")
    project_root = config.get("project_root")

    if not tenant_id:
        print_error("No tenant configured. Run 'gtm init' first.")
        raise SystemExit(1)

    passphrase = resolve_passphrase(passphrase)
    if not passphrase:
        passphrase = click.prompt("Vault passphrase", hide_input=True)

    provider = provider.lower().strip()

    # Resolve endpoint from smart flags or explicit endpoint
    req_method = method or "POST"
    req_endpoint = endpoint
    req_data = None
    req_params = None

    if data_str:
        req_data = json.loads(data_str)
    if params_str:
        req_params = json.loads(params_str)

    # Smart endpoint mapping
    if not req_endpoint:
        provider_map = ENDPOINT_MAP.get(provider, {})
        if email and "email" in provider_map:
            req_method, req_endpoint, data_fn = provider_map["email"]
            result_data = data_fn(email)
            if req_method == "GET":
                req_params = result_data
            else:
                req_data = result_data
        elif domain and "domain" in provider_map:
            req_method, req_endpoint, data_fn = provider_map["domain"]
            result_data = data_fn(domain)
            if req_method == "GET":
                req_params = result_data
            else:
                req_data = result_data
        elif linkedin and "linkedin" in provider_map:
            req_method, req_endpoint, data_fn = provider_map["linkedin"]
            result_data = data_fn(linkedin)
            if req_method == "GET":
                req_params = result_data
            else:
                req_data = result_data
        elif company and "company" in provider_map:
            req_method, req_endpoint, data_fn = provider_map["company"]
            result_data = data_fn(company)
            if req_method == "GET":
                req_params = result_data
            else:
                req_data = result_data
        else:
            print_error(
                f"No smart mapping for {provider}. "
                f"Use --endpoint to specify the API path directly."
            )
            raise SystemExit(1)

    # Show cost estimate
    per_record = COST_ESTIMATES.get(provider, 3.0)
    if not as_json:
        console.print()
        console.print(f"  Provider: [bold]{provider}[/bold]")
        console.print(f"  Endpoint: {req_method} {req_endpoint}")
        console.print(f"  {cost_estimate(provider, 1, per_record)}")
        console.print()
        console.print("  Enriching...", end=" ")

    try:
        sys.path.insert(0, str(project_root or Path(__file__).resolve().parent.parent.parent))
        from vault.tenant import TenantVault
        from vault.tenant_proxy import TenantProxy

        tv = TenantVault(base_path=Path(vault_base) if vault_base else None)
        tv.unlock_tenant(tenant_id, passphrase)
        proxy = TenantProxy(tv)

        start_time = time.time()
        result = proxy.call(
            tenant_id=tenant_id,
            provider=provider,
            method=req_method,
            endpoint=req_endpoint,
            data=req_data,
            params=req_params,
        )
        duration = time.time() - start_time

        status_code = result.get("status_code", 0)
        success = 200 <= status_code < 300
        has_data = bool(result.get("data")) and not result.get("error")

        # Track intelligence
        track_enrichment(
            provider=provider,
            success=success,
            records=1,
            hits=1 if has_data and success else 0,
            cost_cents=per_record if success else 0,
        )

        if as_json:
            click.echo(json.dumps(result, indent=2))
            return

        if success:
            console.print("[green bold]done[/green bold]")
            console.print()
            # Pretty print the response
            data = result.get("data", {})
            console.print_json(json.dumps(data, indent=2))
            console.print()
            # Receipt
            receipt = enrichment_receipt(
                provider=provider,
                records=1,
                hits=1 if has_data else 0,
                cost_cents=per_record,
                duration_secs=duration,
            )
            console.print(receipt)
        else:
            console.print("[red bold]failed[/red bold]")
            console.print()
            error = result.get("error") or result.get("data", {})
            print_error(f"Status {status_code}: {error}")

    except ImportError as e:
        if not as_json:
            console.print("[red bold]error[/red bold]")
        print_error(f"Cannot import vault modules: {e}")
        raise SystemExit(1)
    except Exception as e:
        if not as_json:
            console.print("[red bold]error[/red bold]")
        print_error(f"Error: {e}")
        raise SystemExit(1)
