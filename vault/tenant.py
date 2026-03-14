"""
Multi-Tenant Vault

Architecture:
                    ┌──────────────────────────┐
                    │    resolve_key(tenant,    │
                    │         provider)         │
                    └─────────┬────────────────┘
                              │
                    ┌─────────▼────────────────┐
                    │   1. Check BYOK keys      │
                    │      (tenant's own vault)  │
                    │                            │
                    │   2. Fallback: platform    │
                    │      keys (our shared      │
                    │      pool)                 │
                    │                            │
                    │   3. No key? → error       │
                    └─────────┬────────────────┘
                              │
                    ┌─────────▼────────────────┐
                    │   Proxy injects key        │
                    │   into HTTP request        │
                    │   (key never exposed)      │
                    └──────────────────────────┘

Each tenant gets:
- Their own encrypted vault (isolated keystore)
- Access to platform keys they haven't overridden
- Usage tracking per provider per tenant
- Full audit trail

Key resolution order:
1. BYOK (tenant's own key for this provider) → used if exists
2. Platform key (shared pool we manage) → fallback
3. VaultError → no key available

This means a tenant can override ANY provider with their own key,
and fall back to platform keys for providers they haven't set up.
"""

import json
import os
import uuid
import hashlib
from pathlib import Path
from typing import Optional
from datetime import datetime

from .vault import Vault, VaultError

import logging
audit_logger = logging.getLogger("vault.audit")


class TenantVault:
    """
    Multi-tenant vault manager.

    Each tenant has an isolated encrypted vault.
    Platform keys live in a separate vault accessible to all tenants.
    """

    def __init__(self, base_path: Optional[Path] = None):
        self.base_path = base_path or Path(__file__).parent.parent / ".vault"
        self.base_path.mkdir(parents=True, exist_ok=True)

        self.tenants_dir = self.base_path / "tenants"
        self.tenants_dir.mkdir(exist_ok=True)

        self.platform_dir = self.base_path / "platform"
        self.registry_file = self.base_path / "tenant_registry.json"

        # Platform vault — holds our shared/pooled keys
        self._platform_vault: Optional[Vault] = None

        # Active tenant vaults (loaded on demand)
        self._tenant_vaults: dict[str, Vault] = {}

        # Load or create registry
        self._load_registry()

    def _load_registry(self):
        """Load tenant registry from disk."""
        if self.registry_file.exists():
            self.registry = json.loads(self.registry_file.read_text())
        else:
            self.registry = {
                "tenants": {},
                "created": datetime.utcnow().isoformat(),
                "version": 1,
            }
            self._save_registry()

    def _save_registry(self):
        """Save tenant registry. Never contains key material."""
        self.registry_file.write_text(json.dumps(self.registry, indent=2))

    # ================================================================
    # PLATFORM VAULT (our managed keys)
    # ================================================================

    def initialize_platform(self, passphrase: str) -> dict:
        """Initialize the platform vault for shared/pooled keys."""
        self._platform_vault = Vault(vault_path=self.platform_dir)

        if (self.platform_dir / "keys.enc").exists():
            self._platform_vault.unlock(passphrase)
            audit_logger.info("PLATFORM_VAULT_UNLOCKED")
            return {"status": "unlocked", "type": "platform"}
        else:
            result = self._platform_vault.initialize(passphrase)
            audit_logger.info("PLATFORM_VAULT_INITIALIZED")
            return {**result, "type": "platform"}

    def store_platform_key(self, provider: str, key_value: str) -> dict:
        """Store a platform-managed key (available to all tenants as fallback)."""
        if not self._platform_vault:
            raise VaultError("Platform vault not initialized. Call initialize_platform() first.")

        result = self._platform_vault.store_key(provider, key_value, key_type="platform")
        audit_logger.info(f"PLATFORM_KEY_STORED | provider={provider}")
        return result

    # ================================================================
    # TENANT MANAGEMENT
    # ================================================================

    def create_tenant(self, name: str, passphrase: str, tenant_id: Optional[str] = None) -> dict:
        """
        Create a new tenant with their own isolated vault.

        Returns tenant_id and status (never key material).
        """
        tid = tenant_id or str(uuid.uuid4())

        if tid in self.registry.get("tenants", {}):
            raise VaultError(f"Tenant already exists: {tid}")

        # Create tenant directory
        tenant_dir = self.tenants_dir / tid
        tenant_dir.mkdir(parents=True, exist_ok=True)

        # Initialize tenant vault with their own passphrase
        tenant_vault = Vault(vault_path=tenant_dir)
        result = tenant_vault.initialize(passphrase)

        # Register tenant (no secrets in registry)
        self.registry["tenants"][tid] = {
            "name": name,
            "created": datetime.utcnow().isoformat(),
            "byok_providers": [],
            "usage": {},
        }
        self._save_registry()

        # Cache the unlocked vault
        self._tenant_vaults[tid] = tenant_vault

        audit_logger.info(f"TENANT_CREATED | tenant={tid} | name={name}")

        return {
            "status": "created",
            "tenant_id": tid,
            "name": name,
            "vault_path": str(tenant_dir),
        }

    def unlock_tenant(self, tenant_id: str, passphrase: str) -> dict:
        """Unlock a tenant's vault."""
        if tenant_id not in self.registry.get("tenants", {}):
            raise VaultError(f"Unknown tenant: {tenant_id}")

        tenant_dir = self.tenants_dir / tenant_id
        tenant_vault = Vault(vault_path=tenant_dir)
        tenant_vault.unlock(passphrase)
        self._tenant_vaults[tenant_id] = tenant_vault

        audit_logger.info(f"TENANT_UNLOCKED | tenant={tenant_id}")
        return {"status": "unlocked", "tenant_id": tenant_id}

    def list_tenants(self) -> dict:
        """List all tenants (never any key material)."""
        tenants = {}
        for tid, info in self.registry.get("tenants", {}).items():
            tenants[tid] = {
                "name": info["name"],
                "created": info["created"],
                "byok_providers": info.get("byok_providers", []),
                "total_calls": sum(info.get("usage", {}).values()),
            }
        return {"tenants": tenants}

    def _get_tenant_vault(self, tenant_id: str) -> Vault:
        """Get an unlocked tenant vault (must be unlocked first)."""
        vault = self._tenant_vaults.get(tenant_id)
        if not vault:
            raise VaultError(
                f"Tenant vault not loaded: {tenant_id}. Call unlock_tenant() first."
            )
        return vault

    # ================================================================
    # BYOK — Tenant adds their own keys
    # ================================================================

    def store_tenant_key(self, tenant_id: str, provider: str, key_value: str) -> dict:
        """
        Store a BYOK key for a specific tenant.
        This key takes priority over any platform key for this provider.
        """
        vault = self._get_tenant_vault(tenant_id)
        result = vault.store_key(provider, key_value, key_type="byok")

        # Update registry
        tenant_info = self.registry["tenants"][tenant_id]
        if provider not in tenant_info.get("byok_providers", []):
            tenant_info.setdefault("byok_providers", []).append(provider)
            self._save_registry()

        audit_logger.info(
            f"BYOK_KEY_STORED | tenant={tenant_id} | provider={provider}"
        )
        return {**result, "key_source": "byok", "tenant_id": tenant_id}

    def delete_tenant_key(self, tenant_id: str, provider: str) -> dict:
        """
        Delete a tenant's BYOK key. They'll fall back to platform key.
        """
        vault = self._get_tenant_vault(tenant_id)
        result = vault.delete_key(provider)

        # Update registry
        tenant_info = self.registry["tenants"][tenant_id]
        byok = tenant_info.get("byok_providers", [])
        if provider in byok:
            byok.remove(provider)
            self._save_registry()

        audit_logger.info(
            f"BYOK_KEY_DELETED | tenant={tenant_id} | provider={provider} | "
            f"will_fallback_to=platform"
        )
        return {**result, "fallback": "platform"}

    def list_tenant_keys(self, tenant_id: str) -> dict:
        """
        List a tenant's key configuration.
        Shows which providers use BYOK vs platform keys.
        Never exposes actual key values.
        """
        vault = self._get_tenant_vault(tenant_id)
        byok_result = vault.list_providers()

        # Get platform providers for comparison
        platform_providers = []
        if self._platform_vault:
            try:
                platform_result = self._platform_vault.list_providers()
                platform_providers = list(platform_result.get("providers", {}).keys())
            except VaultError:
                pass

        # Build combined view
        key_map = {}

        # Platform keys (available as fallback)
        for p in platform_providers:
            key_map[p] = {"source": "platform", "status": "available"}

        # BYOK keys (override platform)
        for p, info in byok_result.get("providers", {}).items():
            key_map[p] = {
                "source": "byok",
                "status": "active",
                "fingerprint": info.get("fingerprint"),
                "stored_at": info.get("stored_at"),
            }

        return {
            "tenant_id": tenant_id,
            "keys": key_map,
            "byok_count": len(byok_result.get("providers", {})),
            "platform_available": len(platform_providers),
        }

    # ================================================================
    # KEY RESOLUTION — The core routing logic
    # ================================================================

    def resolve_key(self, tenant_id: str, provider: str) -> tuple[str, str]:
        """
        Resolve which key to use for a tenant+provider combination.

        Resolution order:
        1. BYOK key (tenant's own) → priority
        2. Platform key (our shared pool) → fallback
        3. VaultError → no key available

        Returns: (key_value, source) where source is "byok" or "platform"

        SECURITY: If a tenant exists in the registry but their vault is locked,
        ALL operations are blocked — no silent fallback to platform keys.

        INTERNAL ONLY — called by TenantProxy, never exposed to callers.
        """
        # SECURITY CHECK: If tenant exists but vault is locked, block entirely.
        # This prevents a locked tenant from silently falling through to
        # platform keys, which would be a privilege escalation.
        if tenant_id in self.registry.get("tenants", {}):
            if tenant_id not in self._tenant_vaults:
                raise VaultError(
                    f"Tenant vault is locked: {tenant_id}. "
                    f"Call unlock_tenant() before making API calls."
                )

        # Try BYOK first
        tenant_vault = self._tenant_vaults.get(tenant_id)
        if tenant_vault:
            try:
                key = tenant_vault.get_key(provider)
                self._track_usage(tenant_id, provider, "byok")
                audit_logger.info(
                    f"KEY_RESOLVED | tenant={tenant_id} | provider={provider} | "
                    f"source=byok"
                )
                return key, "byok"
            except VaultError:
                pass  # No BYOK key, try platform

        # Fallback to platform
        if self._platform_vault:
            try:
                key = self._platform_vault.get_key(provider)
                self._track_usage(tenant_id, provider, "platform")
                audit_logger.info(
                    f"KEY_RESOLVED | tenant={tenant_id} | provider={provider} | "
                    f"source=platform"
                )
                return key, "platform"
            except VaultError:
                pass

        raise VaultError(
            f"No key available for provider '{provider}' "
            f"(tenant={tenant_id}). Add a BYOK key or ask admin to add a platform key."
        )

    def _track_usage(self, tenant_id: str, provider: str, source: str):
        """Track API call usage per tenant per provider."""
        tenant_info = self.registry.get("tenants", {}).get(tenant_id)
        if tenant_info:
            usage = tenant_info.setdefault("usage", {})
            usage_key = f"{provider}:{source}"
            usage[usage_key] = usage.get(usage_key, 0) + 1
            self._save_registry()

    def get_usage(self, tenant_id: str) -> dict:
        """Get usage stats for a tenant. No key material."""
        tenant_info = self.registry.get("tenants", {}).get(tenant_id, {})
        raw_usage = tenant_info.get("usage", {})

        # Parse into structured format
        by_provider = {}
        for usage_key, count in raw_usage.items():
            provider, source = usage_key.rsplit(":", 1)
            if provider not in by_provider:
                by_provider[provider] = {"byok_calls": 0, "platform_calls": 0, "total": 0}
            if source == "byok":
                by_provider[provider]["byok_calls"] = count
            else:
                by_provider[provider]["platform_calls"] = count
            by_provider[provider]["total"] += count

        return {
            "tenant_id": tenant_id,
            "usage": by_provider,
            "total_calls": sum(v["total"] for v in by_provider.values()),
        }

    # ================================================================
    # CLEANUP
    # ================================================================

    def lock_tenant(self, tenant_id: str) -> dict:
        """Lock a tenant's vault."""
        vault = self._tenant_vaults.pop(tenant_id, None)
        if vault:
            vault.lock()
        audit_logger.info(f"TENANT_LOCKED | tenant={tenant_id}")
        return {"status": "locked", "tenant_id": tenant_id}

    def lock_all(self) -> dict:
        """Lock everything — platform + all tenants."""
        for tid in list(self._tenant_vaults.keys()):
            self.lock_tenant(tid)
        if self._platform_vault:
            self._platform_vault.lock()
            self._platform_vault = None
        audit_logger.info("ALL_VAULTS_LOCKED")
        return {"status": "all_locked"}
