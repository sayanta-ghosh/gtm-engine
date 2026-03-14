"""
Multi-Tenant Secure Proxy

Wraps the single-tenant proxy with tenant-aware key resolution.

Usage:
    proxy = TenantProxy(tenant_vault)

    # This call:
    # 1. Resolves the key (BYOK first, platform fallback)
    # 2. Injects it into the HTTP request
    # 3. Tracks usage for billing
    # 4. Returns only the response (never the key)
    result = proxy.call("tenant-123", "apollo", "GET", "/people/match",
                        data={"email": "test@example.com"})
"""

import json
import logging
from typing import Optional

import requests

from .vault import VaultError
from .tenant import TenantVault
from .proxy import PROVIDER_AUTH_CONFIG

audit_logger = logging.getLogger("vault.audit")


class TenantProxy:
    """
    Multi-tenant HTTP proxy with BYOK/platform key resolution.

    Same security guarantees as SecureProxy, plus:
    - Tenant isolation (tenant A cannot use tenant B's keys)
    - BYOK priority (user's own keys used first)
    - Platform fallback (our keys used if no BYOK)
    - Per-tenant usage tracking
    - Key source included in response metadata (but never the key itself)
    """

    def __init__(self, tenant_vault: TenantVault):
        self.tenant_vault = tenant_vault
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "GTMEngine/1.0",
            "Accept": "application/json",
        })

    def _inject_auth(
        self, tenant_id: str, provider: str, headers: dict, params: dict
    ) -> tuple[dict, dict, str]:
        """
        Resolve + inject key for a tenant+provider combo.
        Returns (headers, params, key_source) — key_source is "byok" or "platform".
        """
        config = PROVIDER_AUTH_CONFIG.get(provider)
        if not config:
            raise VaultError(
                f"Unknown provider: {provider}. "
                f"Supported: {list(PROVIDER_AUTH_CONFIG.keys())}"
            )

        # Resolve key (BYOK → platform → error)
        key, source = self.tenant_vault.resolve_key(tenant_id, provider)

        method = config["auth_method"]
        if method == "header":
            headers[config["header_name"]] = key
        elif method == "bearer":
            headers["Authorization"] = f"Bearer {key}"
        elif method == "query_param":
            params[config["param_name"]] = key

        # key goes out of scope after return
        return headers, params, source

    def _scrub_secrets(self, text: str, tenant_id: str, provider: str) -> str:
        """Scrub any leaked key material from text."""
        try:
            key, _ = self.tenant_vault.resolve_key(tenant_id, provider)
            if key in text:
                text = text.replace(key, "[REDACTED]")
            if len(key) > 16:
                text = text.replace(key[:8], "[REDACT-START]")
                text = text.replace(key[-8:], "[REDACT-END]")
        except Exception:
            pass
        return text

    def _build_url(self, provider: str, endpoint: str) -> str:
        """Build full URL from provider config."""
        config = PROVIDER_AUTH_CONFIG.get(provider, {})
        base = config.get("base_url", "")
        if endpoint.startswith("http"):
            return endpoint
        return f"{base.rstrip('/')}/{endpoint.lstrip('/')}"

    def call(
        self,
        tenant_id: str,
        provider: str,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """
        Make an authenticated API call for a specific tenant.

        The response includes:
        - status_code, data, provider, endpoint (standard)
        - key_source: "byok" or "platform" (so tenant knows which key was used)
        - tenant_id: which tenant made the call

        SECURITY: Never includes the actual key.
        """
        headers = dict(extra_headers or {})
        params = dict(params or {})

        # Resolve + inject auth
        headers, params, key_source = self._inject_auth(
            tenant_id, provider, headers, params
        )

        url = self._build_url(provider, endpoint)

        audit_logger.info(
            f"TENANT_PROXY_CALL | tenant={tenant_id} | provider={provider} | "
            f"method={method} | endpoint={endpoint} | key_source={key_source}"
        )

        try:
            response = self._session.request(
                method=method.upper(),
                url=url,
                json=data,
                params=params,
                headers=headers,
                timeout=timeout,
            )

            try:
                response_data = response.json()
            except ValueError:
                response_data = {"raw": response.text[:500]}

            result = {
                "status_code": response.status_code,
                "data": response_data,
                "provider": provider,
                "endpoint": endpoint,
                "tenant_id": tenant_id,
                "key_source": key_source,
            }

            # Scrub any leaked key material
            result_str = json.dumps(result)
            scrubbed = self._scrub_secrets(result_str, tenant_id, provider)
            if scrubbed != result_str:
                audit_logger.warning(
                    f"TENANT_KEY_LEAK_SCRUBBED | tenant={tenant_id} | "
                    f"provider={provider}"
                )
                result = json.loads(scrubbed)

            audit_logger.info(
                f"TENANT_PROXY_RESPONSE | tenant={tenant_id} | "
                f"provider={provider} | status={response.status_code} | "
                f"key_source={key_source}"
            )

            return result

        except requests.RequestException as e:
            error_msg = self._scrub_secrets(str(e), tenant_id, provider)
            audit_logger.error(
                f"TENANT_PROXY_ERROR | tenant={tenant_id} | "
                f"provider={provider} | error={error_msg}"
            )
            return {
                "status_code": 0,
                "error": error_msg,
                "provider": provider,
                "endpoint": endpoint,
                "tenant_id": tenant_id,
                "key_source": key_source,
            }

    def check_tenant_provider(self, tenant_id: str, provider: str) -> dict:
        """
        Check what key a tenant would use for a provider.
        Returns source info (never the key itself).
        """
        config = PROVIDER_AUTH_CONFIG.get(provider)
        if not config:
            return {
                "tenant_id": tenant_id,
                "provider": provider,
                "available": False,
                "reason": "Unknown provider",
            }

        try:
            _, source = self.tenant_vault.resolve_key(tenant_id, provider)
            return {
                "tenant_id": tenant_id,
                "provider": provider,
                "available": True,
                "key_source": source,
                "base_url": config["base_url"],
            }
        except VaultError:
            return {
                "tenant_id": tenant_id,
                "provider": provider,
                "available": False,
                "reason": "No BYOK or platform key",
            }

    def check_all_providers(self, tenant_id: str) -> dict:
        """Check which providers a tenant has access to and via which source."""
        results = {}
        for provider in PROVIDER_AUTH_CONFIG:
            results[provider] = self.check_tenant_provider(tenant_id, provider)
        return {"tenant_id": tenant_id, "providers": results}
