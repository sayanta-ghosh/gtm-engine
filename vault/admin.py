"""
Admin Interface — Platform Key & Tenant Management

This is YOUR console. As the platform admin, you:
- Manage the default/platform API keys available to all tenants
- Create, suspend, and manage tenants
- Monitor usage across all tenants
- Set spend caps and plan types
- See which keys are being overridden by BYOK

Security model:
- Admin passphrase required to unlock
- Admin can see key fingerprints + metadata, NEVER raw values
- Admin can see all tenants' usage but NOT their BYOK key values
- All admin actions are audit logged

Usage via Claude:
    admin = AdminConsole(base_path)
    admin.unlock("admin-passphrase")
    admin.add_platform_key("apollo", "sk-xxx")       # encrypted immediately
    admin.dashboard()                                  # full overview
"""

import json
from typing import Optional
from pathlib import Path
from datetime import datetime

from .tenant import TenantVault, VaultError
from .proxy import PROVIDER_AUTH_CONFIG

import logging
audit_logger = logging.getLogger("vault.audit")


class AdminConsole:
    """
    Platform admin interface.

    You (the admin) manage:
    1. Platform keys — the default keys available to all tenants
    2. Tenants — create, manage, monitor
    3. Spend caps — per-tenant limits
    4. Provider catalog — which providers are available
    """

    def __init__(self, base_path: Optional[Path] = None):
        self.tv = TenantVault(base_path=base_path)
        self._unlocked = False

    # ================================================================
    # INITIALIZATION & AUTH
    # ================================================================

    def unlock(self, platform_passphrase: str) -> dict:
        """
        Unlock the admin console with the platform passphrase.
        Must be called before any admin operations.
        """
        try:
            result = self.tv.initialize_platform(platform_passphrase)
            self._unlocked = True
            audit_logger.info("ADMIN_CONSOLE_UNLOCKED")
            return {"success": True, "status": result.get("status")}
        except VaultError as e:
            return {"success": False, "error": str(e)}

    def _require_admin(self):
        if not self._unlocked:
            raise VaultError("Admin console locked. Call unlock() first.")

    # ================================================================
    # PLATFORM KEY MANAGEMENT
    # ================================================================

    def add_platform_key(self, provider: str, key_value: str) -> dict:
        """
        Add or update a platform key.

        This key becomes the DEFAULT for all tenants who haven't
        added their own BYOK key for this provider.

        The key is encrypted immediately — even you can't read it back.
        """
        self._require_admin()

        if provider not in PROVIDER_AUTH_CONFIG:
            return {
                "success": False,
                "error": f"Unknown provider: {provider}",
                "supported": list(PROVIDER_AUTH_CONFIG.keys()),
            }

        try:
            result = self.tv.store_platform_key(provider, key_value)
            audit_logger.info(f"ADMIN_PLATFORM_KEY_ADDED | provider={provider}")
            return {
                "success": True,
                "message": f"Platform key for {provider} is now active.",
                "provider": provider,
                "fingerprint": result["fingerprint"],
                "note": "All tenants without a BYOK key for this provider will use this key.",
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    def rotate_platform_key(self, provider: str, new_key_value: str) -> dict:
        """Rotate a platform key. Old key is destroyed."""
        self._require_admin()
        try:
            # Delete old
            try:
                self.tv._platform_vault.delete_key(provider)
            except VaultError:
                pass
            result = self.tv.store_platform_key(provider, new_key_value)
            audit_logger.info(f"ADMIN_PLATFORM_KEY_ROTATED | provider={provider}")
            return {
                "success": True,
                "message": f"Platform key for {provider} rotated.",
                "new_fingerprint": result["fingerprint"],
                "warning": "All tenants using the platform key for this provider are now on the new key.",
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    def remove_platform_key(self, provider: str) -> dict:
        """
        Remove a platform key.
        Tenants with BYOK are unaffected. Tenants WITHOUT BYOK lose access.
        """
        self._require_admin()
        try:
            self.tv._platform_vault.delete_key(provider)
            # Find affected tenants
            affected = []
            for tid, info in self.tv.registry.get("tenants", {}).items():
                if provider not in info.get("byok_providers", []):
                    affected.append(tid)

            audit_logger.info(
                f"ADMIN_PLATFORM_KEY_REMOVED | provider={provider} | "
                f"affected_tenants={len(affected)}"
            )
            return {
                "success": True,
                "message": f"Platform key for {provider} removed.",
                "affected_tenants": affected,
                "warning": f"{len(affected)} tenant(s) will lose {provider} access unless they add their own key.",
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    def list_platform_keys(self) -> dict:
        """
        List all platform keys.
        Shows fingerprints and metadata — NEVER actual key values.
        """
        self._require_admin()
        try:
            result = self.tv._platform_vault.list_providers()
            providers = result.get("providers", {})

            # Enrich with override info
            enriched = {}
            for provider, meta in providers.items():
                # Count how many tenants override this with BYOK
                overrides = 0
                using_platform = 0
                for tid, info in self.tv.registry.get("tenants", {}).items():
                    if provider in info.get("byok_providers", []):
                        overrides += 1
                    else:
                        using_platform += 1

                enriched[provider] = {
                    **meta,
                    "tenants_using_platform": using_platform,
                    "tenants_with_byok_override": overrides,
                }

            return {
                "success": True,
                "platform_keys": enriched,
                "total": len(enriched),
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    # ================================================================
    # TENANT MANAGEMENT
    # ================================================================

    def create_tenant(self, name: str, passphrase: str, plan: str = "byok",
                      spend_cap_cents: Optional[int] = None,
                      tenant_id: Optional[str] = None) -> dict:
        """
        Create a new tenant.

        Plans:
        - "byok"    → Tenant uses own keys only
        - "managed" → Tenant uses platform keys only
        - "both"    → Tenant can use BYOK (priority) + platform (fallback)
        """
        self._require_admin()
        try:
            result = self.tv.create_tenant(name, passphrase, tenant_id)
            tid = result["tenant_id"]

            # Set plan and spend cap in registry
            tenant_info = self.tv.registry["tenants"][tid]
            tenant_info["plan"] = plan
            tenant_info["spend_cap_cents"] = spend_cap_cents
            self.tv._save_registry()

            audit_logger.info(
                f"ADMIN_TENANT_CREATED | tenant={tid} | name={name} | plan={plan}"
            )
            return {
                "success": True,
                "tenant_id": tid,
                "name": name,
                "plan": plan,
                "spend_cap": f"${spend_cap_cents/100:.2f}/mo" if spend_cap_cents else "unlimited",
            }
        except VaultError as e:
            return {"success": False, "error": str(e)}

    def update_tenant(self, tenant_id: str, plan: Optional[str] = None,
                      spend_cap_cents: Optional[int] = None,
                      name: Optional[str] = None) -> dict:
        """Update tenant settings."""
        self._require_admin()
        tenant_info = self.tv.registry.get("tenants", {}).get(tenant_id)
        if not tenant_info:
            return {"success": False, "error": f"Unknown tenant: {tenant_id}"}

        changes = {}
        if plan is not None:
            tenant_info["plan"] = plan
            changes["plan"] = plan
        if spend_cap_cents is not None:
            tenant_info["spend_cap_cents"] = spend_cap_cents
            changes["spend_cap"] = f"${spend_cap_cents/100:.2f}/mo"
        if name is not None:
            tenant_info["name"] = name
            changes["name"] = name

        self.tv._save_registry()
        audit_logger.info(f"ADMIN_TENANT_UPDATED | tenant={tenant_id} | changes={changes}")
        return {"success": True, "tenant_id": tenant_id, "changes": changes}

    def suspend_tenant(self, tenant_id: str) -> dict:
        """Suspend a tenant — locks vault, blocks all API calls."""
        self._require_admin()
        tenant_info = self.tv.registry.get("tenants", {}).get(tenant_id)
        if not tenant_info:
            return {"success": False, "error": f"Unknown tenant: {tenant_id}"}

        self.tv.lock_tenant(tenant_id)
        tenant_info["status"] = "suspended"
        tenant_info["suspended_at"] = datetime.utcnow().isoformat()
        self.tv._save_registry()

        audit_logger.info(f"ADMIN_TENANT_SUSPENDED | tenant={tenant_id}")
        return {
            "success": True,
            "message": f"Tenant {tenant_id} has been suspended. All API calls blocked.",
        }

    def reactivate_tenant(self, tenant_id: str, passphrase: str) -> dict:
        """Reactivate a suspended tenant."""
        self._require_admin()
        tenant_info = self.tv.registry.get("tenants", {}).get(tenant_id)
        if not tenant_info:
            return {"success": False, "error": f"Unknown tenant: {tenant_id}"}

        try:
            self.tv.unlock_tenant(tenant_id, passphrase)
            tenant_info["status"] = "active"
            tenant_info.pop("suspended_at", None)
            self.tv._save_registry()

            audit_logger.info(f"ADMIN_TENANT_REACTIVATED | tenant={tenant_id}")
            return {"success": True, "message": f"Tenant {tenant_id} reactivated."}
        except VaultError as e:
            return {"success": False, "error": str(e)}

    # ================================================================
    # MONITORING & DASHBOARD
    # ================================================================

    def dashboard(self) -> dict:
        """
        Admin dashboard — full overview of platform health.

        Shows:
        - Platform keys and their status
        - All tenants with usage summary
        - BYOK override map (who's using what)
        - Total API calls across platform
        """
        self._require_admin()

        # Platform keys
        platform_keys = self.list_platform_keys()

        # Tenant overview
        tenants = []
        total_calls = 0
        for tid, info in self.tv.registry.get("tenants", {}).items():
            usage = self.tv.get_usage(tid)
            calls = usage.get("total_calls", 0)
            total_calls += calls

            tenants.append({
                "tenant_id": tid,
                "name": info["name"],
                "plan": info.get("plan", "byok"),
                "status": info.get("status", "active"),
                "byok_providers": info.get("byok_providers", []),
                "total_calls": calls,
                "spend_cap": info.get("spend_cap_cents"),
                "created": info["created"],
            })

        # BYOK override map — which tenants override which providers
        override_map = {}
        for provider in PROVIDER_AUTH_CONFIG:
            overriders = [
                t["name"] for t in tenants
                if provider in t.get("byok_providers", [])
            ]
            if overriders:
                override_map[provider] = overriders

        return {
            "success": True,
            "platform_keys": platform_keys.get("platform_keys", {}),
            "tenants": tenants,
            "tenant_count": len(tenants),
            "total_api_calls": total_calls,
            "byok_overrides": override_map,
            "timestamp": datetime.utcnow().isoformat(),
        }

    def tenant_detail(self, tenant_id: str) -> dict:
        """Deep-dive into a specific tenant's configuration and usage."""
        self._require_admin()

        tenant_info = self.tv.registry.get("tenants", {}).get(tenant_id)
        if not tenant_info:
            return {"success": False, "error": f"Unknown tenant: {tenant_id}"}

        usage = self.tv.get_usage(tenant_id)

        # Build provider-level view
        providers = {}
        for provider in PROVIDER_AUTH_CONFIG:
            is_byok = provider in tenant_info.get("byok_providers", [])
            provider_usage = usage.get("usage", {}).get(provider, {})

            providers[provider] = {
                "key_source": "byok" if is_byok else "platform",
                "overridden": is_byok,
                "calls": provider_usage.get("total", 0),
                "byok_calls": provider_usage.get("byok_calls", 0),
                "platform_calls": provider_usage.get("platform_calls", 0),
            }

        return {
            "success": True,
            "tenant_id": tenant_id,
            "name": tenant_info["name"],
            "plan": tenant_info.get("plan", "byok"),
            "status": tenant_info.get("status", "active"),
            "spend_cap_cents": tenant_info.get("spend_cap_cents"),
            "created": tenant_info["created"],
            "providers": providers,
            "total_calls": usage.get("total_calls", 0),
        }
