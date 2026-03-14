"""
gtm add-key — Store a BYOK API key securely

The key is encrypted immediately and never stored in plain text.
"""

import sys
import click
from pathlib import Path

from ..config import load_config, resolve_passphrase
from ..output import console, print_success, print_error, print_info


@click.command()
@click.argument("provider")
@click.argument("key", required=False, default=None)
@click.option("--passphrase", default=None, help="Vault passphrase (or set GTM_PASSPHRASE)")
def add_key(provider, key, passphrase):
    """Store a BYOK API key for PROVIDER.

    The key is encrypted immediately via AES-256 and can never be retrieved.
    This key takes priority over any platform key for this provider.

    Examples:
        gtm add-key apollo
        gtm add-key rocketreach
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

    # Prompt for key if not provided
    if not key:
        key = click.prompt(f"Paste your {provider} API key (hidden)", hide_input=True)

    if not key.strip():
        print_error("No key provided.")
        raise SystemExit(1)

    try:
        sys.path.insert(0, str(project_root or Path(__file__).resolve().parent.parent.parent))
        from vault.tenant import TenantVault
        from vault.key_manager import KeyManager
        from vault.proxy import PROVIDER_AUTH_CONFIG

        provider = provider.lower().strip()
        if provider not in PROVIDER_AUTH_CONFIG:
            print_error(f"Unknown provider: {provider}")
            console.print(f"  Supported: {', '.join(PROVIDER_AUTH_CONFIG.keys())}")
            raise SystemExit(1)

        tv = TenantVault(base_path=Path(vault_base) if vault_base else None)
        tv.unlock_tenant(tenant_id, passphrase)
        km = KeyManager(tv)

        result = km.add_key(tenant_id, provider, key.strip())

        if result.get("success"):
            print_success(
                f"{provider} key stored securely "
                f"(fingerprint: {result.get('fingerprint', '?')[:12]})"
            )
            print_info(f"Test with: gtm enrich --provider {provider}")
        else:
            print_error(f"Failed: {result.get('error', 'Unknown error')}")
            raise SystemExit(1)

    except ImportError as e:
        print_error(f"Cannot import vault modules: {e}")
        raise SystemExit(1)
    except Exception as e:
        print_error(f"Error: {e}")
        raise SystemExit(1)
