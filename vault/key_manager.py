"""
Key Management Interface

This module provides the user-facing interface for managing API keys.
It's what Claude calls when a user says "add my Apollo key" or
"show me which keys I'm using."

Design principles:
- Users see: provider name, source (BYOK/platform), fingerprint, usage
- Users NEVER see: the actual key value
- Users can: add, rotate, delete their BYOK keys
- Users cannot: access other tenants' keys or see platform key values

This can be:
1. Called directly by Claude via skills
2. Wrapped as an MCP tool
3. Exposed via CLI
"""

import json
import getpass
from typing import Optional
from pathlib import Path

from .tenant import TenantVault, VaultError
from .tenant_proxy import TenantProxy
from .proxy import PROVIDER_AUTH_CONFIG


class KeyManager:
    """
    User-facing key management interface.

    All methods return dicts suitable for Claude to present to users.
    No method ever returns actual key material.
    """

    def __init__(self, tenant_vault: TenantVault):
        self.tv = tenant_vault
        self.proxy = TenantProxy(tenant_vault)

    # ================================================================
    # ONBOARDING — First-time setup
    # ================================================================

    def onboard_tenant(self, name: str, passphrase: str, tenant_id: Optional[str] = None) -> dict:
        """
        Create a new tenant account.

        Called when a new user sets up the GTM engine for the first time.
        Claude walks them through this conversationally.
        """
        try:
            result = self.tv.create_tenant(name, passphrase, tenant_id)
            return {
                "success": True,
                "message": f"Welcome, {name}! Your GTM engine is set up.",
                "tenant_id": result["tenant_id"],
                "next_steps": [
                    "Add your API keys for enrichment providers (Apollo, PDL, Hunter, etc.)",
                    "Or use platform keys to get started immediately",
                    "Set up your ICP context in .gtm/context.md",
                ],
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    # ================================================================
    # KEY MANAGEMENT — Add, rotate, delete BYOK keys
    # ================================================================

    def add_key(self, tenant_id: str, provider: str, key_value: str) -> dict:
        """
        Add a BYOK key for a provider.

        Called when user says: "Add my Apollo API key"
        The key_value is encrypted immediately and never returned.
        """
        # Validate provider
        if provider not in PROVIDER_AUTH_CONFIG:
            return {
                "success": False,
                "error": f"Unknown provider: {provider}",
                "supported": list(PROVIDER_AUTH_CONFIG.keys()),
            }

        try:
            result = self.tv.store_tenant_key(tenant_id, provider, key_value)
            return {
                "success": True,
                "message": f"Your {provider} API key has been securely stored.",
                "provider": provider,
                "fingerprint": result["fingerprint"],
                "key_source": "byok",
                "note": "This key will be used instead of any platform key for this provider.",
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    def rotate_key(self, tenant_id: str, provider: str, new_key_value: str) -> dict:
        """
        Rotate a BYOK key — old key is replaced, never retrievable.
        """
        try:
            # Delete old, store new
            try:
                self.tv.delete_tenant_key(tenant_id, provider)
            except VaultError:
                pass  # No existing key, that's fine
            result = self.tv.store_tenant_key(tenant_id, provider, new_key_value)
            return {
                "success": True,
                "message": f"Your {provider} key has been rotated.",
                "new_fingerprint": result["fingerprint"],
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    def remove_key(self, tenant_id: str, provider: str) -> dict:
        """
        Remove a BYOK key. Tenant falls back to platform key.
        """
        try:
            self.tv.delete_tenant_key(tenant_id, provider)
            # Check if platform key exists
            has_fallback = False
            try:
                self.tv.resolve_key(tenant_id, provider)
                has_fallback = True
            except VaultError:
                pass

            return {
                "success": True,
                "message": f"Your {provider} key has been removed.",
                "fallback": "platform" if has_fallback else "none",
                "warning": None if has_fallback else f"No platform key available for {provider}. This provider is now unavailable.",
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    # ================================================================
    # STATUS & VISIBILITY
    # ================================================================

    def show_keys(self, tenant_id: str) -> dict:
        """
        Show key configuration for a tenant.

        Called when user says: "Show me my keys" or "What providers do I have?"
        Returns source and fingerprint — NEVER actual key values.
        """
        try:
            key_info = self.tv.list_tenant_keys(tenant_id)
            usage = self.tv.get_usage(tenant_id)

            # Build a user-friendly view
            providers = []
            for provider_name, config in PROVIDER_AUTH_CONFIG.items():
                key_data = key_info["keys"].get(provider_name, {})
                usage_data = usage.get("usage", {}).get(provider_name, {})

                providers.append({
                    "provider": provider_name,
                    "source": key_data.get("source", "not configured"),
                    "status": key_data.get("status", "unavailable"),
                    "fingerprint": key_data.get("fingerprint", "-"),
                    "total_calls": usage_data.get("total", 0),
                    "base_url": config["base_url"],
                })

            return {
                "success": True,
                "tenant_id": tenant_id,
                "providers": providers,
                "summary": {
                    "byok": key_info["byok_count"],
                    "platform": key_info["platform_available"],
                    "total_available": key_info["byok_count"] + key_info["platform_available"],
                },
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    def check_provider(self, tenant_id: str, provider: str) -> dict:
        """
        Check if a specific provider is available and which key source will be used.
        """
        return self.proxy.check_tenant_provider(tenant_id, provider)

    def show_usage(self, tenant_id: str) -> dict:
        """Show API usage stats for a tenant."""
        try:
            return self.tv.get_usage(tenant_id)
        except VaultError as e:
            return {"success": False, "error": str(e)}

    # ================================================================
    # PROVIDER INFO
    # ================================================================

    def list_supported_providers(self) -> dict:
        """List all supported enrichment/sequencing providers."""
        providers = []
        for name, config in PROVIDER_AUTH_CONFIG.items():
            providers.append({
                "provider": name,
                "base_url": config["base_url"],
                "auth_method": config["auth_method"],
            })
        return {"supported_providers": providers}

    # ================================================================
    # INTERACTIVE CLI
    # ================================================================

    def interactive_add_key(self, tenant_id: str) -> dict:
        """
        Interactive key addition — prompts user for provider and key.
        For use in terminal/CLI mode (not via Claude).
        """
        print("\n📋 Supported providers:")
        for i, name in enumerate(PROVIDER_AUTH_CONFIG.keys(), 1):
            print(f"   {i}. {name}")

        provider = input("\nProvider name: ").strip().lower()
        if provider not in PROVIDER_AUTH_CONFIG:
            return {"success": False, "error": f"Unknown provider: {provider}"}

        # Use getpass so key doesn't show in terminal
        key_value = getpass.getpass(f"Paste your {provider} API key (hidden): ")

        if not key_value.strip():
            return {"success": False, "error": "No key provided"}

        return self.add_key(tenant_id, provider, key_value.strip())

    # ================================================================
    # BULK OPERATIONS
    # ================================================================

    def bulk_add_keys(self, tenant_id: str, keys: dict[str, str]) -> dict:
        """
        Add multiple BYOK keys at once.
        keys = {"apollo": "key1", "pdl": "key2", ...}
        """
        results = {}
        for provider, key_value in keys.items():
            results[provider] = self.add_key(tenant_id, provider, key_value)
        return {
            "success": all(r.get("success") for r in results.values()),
            "results": results,
        }

    def export_config(self, tenant_id: str) -> dict:
        """
        Export tenant config (for backup/migration).
        Exports METADATA ONLY — never actual keys.
        """
        try:
            keys = self.show_keys(tenant_id)
            usage = self.show_usage(tenant_id)
            return {
                "success": True,
                "tenant_id": tenant_id,
                "config": {
                    "providers": keys.get("providers", []),
                    "usage": usage.get("usage", {}),
                },
                "note": "This export contains metadata only. API keys must be re-added after migration.",
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}
