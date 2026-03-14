"""
Tenant Console — User-Facing Key & Provider Management

This is what YOUR USERS see. Each tenant can:
- View which providers they have access to
- See which are using their own keys vs platform defaults
- Add their own API keys (BYOK) to override platform defaults
- Remove their BYOK keys to fall back to platform defaults
- See their usage and costs

What tenants CANNOT do:
- See platform key values
- See other tenants' anything
- Modify platform keys
- Change their own plan or spend cap (admin only)

Usage via Claude:
    console = TenantConsole(tenant_vault, tenant_id="t-123")
    console.unlock("my-passphrase")
    console.my_providers()                          # see all providers
    console.use_my_key("apollo", "sk-xxx")          # override with BYOK
    console.use_platform_key("apollo")              # revert to platform default
"""

import json
from typing import Optional
from pathlib import Path
from datetime import datetime

from .tenant import TenantVault, VaultError
from .tenant_proxy import TenantProxy
from .proxy import PROVIDER_AUTH_CONFIG

import logging
audit_logger = logging.getLogger("vault.audit")


class TenantConsole:
    """
    Tenant-facing console.

    Each tenant instance is scoped to a single tenant_id.
    They can only see and manage their own keys.
    """

    def __init__(self, tenant_vault: TenantVault, tenant_id: str):
        self.tv = tenant_vault
        self.tenant_id = tenant_id
        self.proxy = TenantProxy(tenant_vault)
        self._unlocked = False

    # ================================================================
    # AUTH
    # ================================================================

    def unlock(self, passphrase: str) -> dict:
        """Unlock this tenant's vault."""
        try:
            self.tv.unlock_tenant(self.tenant_id, passphrase)
            self._unlocked = True
            return {
                "success": True,
                "message": "Your vault is unlocked. You can now manage keys and make API calls.",
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    def _require_unlocked(self):
        if not self._unlocked:
            raise VaultError("Your vault is locked. Call unlock() first.")

    # ================================================================
    # PROVIDER OVERVIEW
    # ================================================================

    def my_providers(self) -> dict:
        """
        Show all providers and which key source each uses.

        Returns a clear view:
        - Which providers use YOUR key (BYOK)
        - Which use the PLATFORM default
        - Which are not available at all

        Claude can present this as a nice table.
        """
        self._require_unlocked()

        try:
            key_info = self.tv.list_tenant_keys(self.tenant_id)
            usage = self.tv.get_usage(self.tenant_id)

            providers = []
            for provider_name, config in PROVIDER_AUTH_CONFIG.items():
                key_data = key_info["keys"].get(provider_name, {})
                usage_data = usage.get("usage", {}).get(provider_name, {})

                source = key_data.get("source", "none")
                status = key_data.get("status", "unavailable")

                providers.append({
                    "provider": provider_name,
                    "using": source,  # "byok" | "platform" | "none"
                    "status": status,
                    "fingerprint": key_data.get("fingerprint", "-"),
                    "calls": usage_data.get("total", 0),
                    "can_override": source == "platform",  # Can add BYOK
                    "can_revert": source == "byok",        # Can go back to platform
                })

            return {
                "success": True,
                "providers": providers,
                "summary": {
                    "using_my_keys": sum(1 for p in providers if p["using"] == "byok"),
                    "using_platform": sum(1 for p in providers if p["using"] == "platform"),
                    "unavailable": sum(1 for p in providers if p["using"] == "none"),
                },
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    # ================================================================
    # BYOK — Use your own keys
    # ================================================================

    def use_my_key(self, provider: str, key_value: str) -> dict:
        """
        Override the platform key with your own API key.

        After this:
        - All enrichment calls for this provider use YOUR key
        - You're billed by the provider directly
        - Platform key is not consumed

        The key is encrypted immediately and can never be retrieved.
        """
        self._require_unlocked()

        if provider not in PROVIDER_AUTH_CONFIG:
            return {
                "success": False,
                "error": f"Unknown provider: {provider}",
                "supported": list(PROVIDER_AUTH_CONFIG.keys()),
            }

        try:
            result = self.tv.store_tenant_key(self.tenant_id, provider, key_value)
            return {
                "success": True,
                "message": f"Now using YOUR {provider} key.",
                "provider": provider,
                "fingerprint": result["fingerprint"],
                "source": "byok",
                "note": "Your calls to this provider now use your key. You pay the provider directly.",
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    def use_platform_key(self, provider: str) -> dict:
        """
        Remove your BYOK key and revert to the platform default.

        After this:
        - Calls use the platform-managed key
        - Usage is charged at platform rates (provider cost + markup)
        """
        self._require_unlocked()

        try:
            self.tv.delete_tenant_key(self.tenant_id, provider)

            # Check if platform key actually exists
            has_platform = False
            try:
                self.tv.resolve_key(self.tenant_id, provider)
                has_platform = True
            except VaultError:
                pass

            if has_platform:
                return {
                    "success": True,
                    "message": f"Reverted to platform key for {provider}.",
                    "source": "platform",
                    "note": "Calls will use the platform key. Usage charged at platform rates.",
                }
            else:
                return {
                    "success": True,
                    "message": f"Your {provider} key removed, but no platform key is available.",
                    "source": "none",
                    "warning": f"{provider} is now unavailable. Add your own key or ask admin for platform access.",
                }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    def rotate_my_key(self, provider: str, new_key_value: str) -> dict:
        """Replace your BYOK key with a new one."""
        self._require_unlocked()

        try:
            # Remove old
            try:
                self.tv.delete_tenant_key(self.tenant_id, provider)
            except VaultError:
                pass

            result = self.tv.store_tenant_key(self.tenant_id, provider, new_key_value)
            return {
                "success": True,
                "message": f"Your {provider} key has been rotated.",
                "new_fingerprint": result["fingerprint"],
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    # ================================================================
    # USAGE & COSTS
    # ================================================================

    def my_usage(self) -> dict:
        """
        Show your API usage broken down by provider and key source.

        Helps answer:
        - How many enrichment calls have I made?
        - Which providers am I using most?
        - Am I using my key or the platform key for each?
        """
        self._require_unlocked()

        try:
            usage = self.tv.get_usage(self.tenant_id)
            tenant_info = self.tv.registry.get("tenants", {}).get(self.tenant_id, {})

            return {
                "success": True,
                **usage,
                "plan": tenant_info.get("plan", "byok"),
                "spend_cap": tenant_info.get("spend_cap_cents"),
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    # ================================================================
    # QUICK CHECKS
    # ================================================================

    def check_provider(self, provider: str) -> dict:
        """
        Quick check — is this provider available, and which key will be used?

        Useful before making an enrichment call to verify access.
        """
        self._require_unlocked()
        return self.proxy.check_tenant_provider(self.tenant_id, provider)

    def check_all(self) -> dict:
        """Check availability of ALL providers at once."""
        self._require_unlocked()
        return self.proxy.check_all_providers(self.tenant_id)

    # ================================================================
    # PROVIDER COMPARISON — Why should I use BYOK?
    # ================================================================

    def byok_vs_platform(self) -> dict:
        """
        Help the user understand the tradeoff between BYOK and platform keys.

        Returns a comparison for each provider showing:
        - Current source
        - Platform pricing (if using managed keys)
        - BYOK benefit (if they switch)
        """
        self._require_unlocked()

        try:
            key_info = self.tv.list_tenant_keys(self.tenant_id)
            usage = self.tv.get_usage(self.tenant_id)

            comparison = []
            for provider in PROVIDER_AUTH_CONFIG:
                key_data = key_info["keys"].get(provider, {})
                source = key_data.get("source", "none")
                provider_usage = usage.get("usage", {}).get(provider, {})

                comparison.append({
                    "provider": provider,
                    "current_source": source,
                    "platform_calls": provider_usage.get("platform_calls", 0),
                    "byok_calls": provider_usage.get("byok_calls", 0),
                    "byok_benefit": "You pay provider directly. No markup." if source != "byok" else "Already using your key.",
                    "platform_benefit": "No setup needed. We handle auth + rate limits." if source != "platform" else "Already using platform key.",
                })

            return {"success": True, "comparison": comparison}
        except VaultError as e:
            return {"success": False, "error": str(e)}
