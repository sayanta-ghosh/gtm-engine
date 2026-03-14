"""
Secure HTTP Proxy for Vault

This is the ONLY way keys should be used. Instead of:
    key = vault.get_key("apollo")          # BAD: key is exposed
    requests.get(url, headers={"X-Api-Key": key})

You use:
    vault_proxy.call("apollo", "GET", url)  # GOOD: key never exposed

The proxy:
1. Reads the key from the vault internally
2. Injects it into the HTTP request via the correct auth method
3. Makes the request
4. Returns ONLY the response data (never the auth headers)
5. Scrubs any key material from error messages
"""

import json
import logging
import re
from typing import Optional, Any
from urllib.parse import urljoin

import requests

from .vault import Vault, VaultError

audit_logger = logging.getLogger("vault.audit")


# Provider auth configurations
# Tells the proxy HOW to inject the key for each provider
PROVIDER_AUTH_CONFIG = {
    "apollo": {
        "base_url": "https://api.apollo.io/api/v1",
        "auth_method": "header",
        "header_name": "X-Api-Key",
    },
    "pdl": {
        "base_url": "https://api.peopledatalabs.com/v5",
        "auth_method": "header",
        "header_name": "X-Api-Key",
    },
    "hunter": {
        "base_url": "https://api.hunter.io/v2",
        "auth_method": "query_param",
        "param_name": "api_key",
    },
    "leadmagic": {
        "base_url": "https://api.leadmagic.io/api/v1",
        "auth_method": "header",
        "header_name": "X-Api-Key",
    },
    "zerobounce": {
        "base_url": "https://api.zerobounce.net/v2",
        "auth_method": "query_param",
        "param_name": "api_key",
    },
    "apify": {
        "base_url": "https://api.apify.com/v2",
        "auth_method": "bearer",
    },
    "firecrawl": {
        "base_url": "https://api.firecrawl.dev/v1",
        "auth_method": "bearer",
    },
    "composio": {
        "base_url": "https://backend.composio.dev/api/v2",
        "auth_method": "header",
        "header_name": "X-API-Key",
    },
    "instantly": {
        "base_url": "https://api.instantly.ai/api/v1",
        "auth_method": "query_param",
        "param_name": "api_key",
    },
    "crustdata": {
        "base_url": "https://api.crustdata.com",
        "auth_method": "bearer",
    },
    "rocketreach": {
        "base_url": "https://api.rocketreach.co/v2/api",
        "auth_method": "header",
        "header_name": "Api-Key",
    },
    "rapidapi_google": {
        "base_url": "https://google-search74.p.rapidapi.com",
        "auth_method": "header",
        "header_name": "X-RapidAPI-Key",
    },
    "parallel": {
        "base_url": "https://api.parallel.ai/v1",
        "auth_method": "bearer",
    },
}


class SecureProxy:
    """
    Makes authenticated API calls without exposing keys.

    The proxy pattern ensures:
    - Keys are injected at request time, never returned
    - Error messages are scrubbed of any key material
    - All access is audit logged
    - Response objects never contain auth headers
    """

    def __init__(self, vault: Vault):
        self.vault = vault
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "GTMEngine/1.0",
            "Accept": "application/json",
        })

    def _inject_auth(self, provider: str, headers: dict, params: dict) -> tuple[dict, dict]:
        """
        Inject the API key into the request using the provider's auth method.
        Returns modified (headers, params) — key is consumed, not stored.
        """
        config = PROVIDER_AUTH_CONFIG.get(provider)
        if not config:
            raise VaultError(f"Unknown provider: {provider}. Supported: {list(PROVIDER_AUTH_CONFIG.keys())}")

        # Get key from vault (internal access — never exposed to caller)
        key = self.vault.get_key(provider)

        method = config["auth_method"]

        if method == "header":
            headers[config["header_name"]] = key
        elif method == "bearer":
            headers["Authorization"] = f"Bearer {key}"
        elif method == "query_param":
            params[config["param_name"]] = key
        else:
            raise VaultError(f"Unknown auth method: {method}")

        # key variable goes out of scope here — Python GC will clean it
        return headers, params

    def _scrub_secrets(self, text: str, provider: str) -> str:
        """
        Remove any accidentally leaked key material from error messages.
        Belt-and-suspenders — should never be needed if proxy works correctly.
        """
        try:
            key = self.vault.get_key(provider)
            if key in text:
                text = text.replace(key, "[REDACTED]")
            # Also scrub partial key matches (first/last 8 chars)
            if len(key) > 16:
                text = text.replace(key[:8], "[REDACT-START]")
                text = text.replace(key[-8:], "[REDACT-END]")
        except Exception:
            pass
        return text

    def _build_url(self, provider: str, endpoint: str) -> str:
        """Build full URL from provider base + endpoint."""
        config = PROVIDER_AUTH_CONFIG.get(provider, {})
        base = config.get("base_url", "")
        if endpoint.startswith("http"):
            return endpoint
        return f"{base.rstrip('/')}/{endpoint.lstrip('/')}"

    def call(
        self,
        provider: str,
        method: str,
        endpoint: str,
        data: Optional[dict] = None,
        params: Optional[dict] = None,
        extra_headers: Optional[dict] = None,
        timeout: int = 30,
    ) -> dict:
        """
        Make an authenticated API call. This is the ONLY public interface.

        Returns:
            {
                "status_code": 200,
                "data": { ... },  # Response JSON
                "provider": "apollo",
                "endpoint": "/people/match"
            }

        SECURITY: Response never includes auth headers or key material.
        """
        headers = dict(extra_headers or {})
        params = dict(params or {})

        # Inject auth (key is consumed internally)
        headers, params = self._inject_auth(provider, headers, params)

        url = self._build_url(provider, endpoint)

        audit_logger.info(
            f"PROXY_CALL | provider={provider} | method={method} | "
            f"endpoint={endpoint}"
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

            # Parse response
            try:
                response_data = response.json()
            except ValueError:
                response_data = {"raw": response.text[:500]}

            result = {
                "status_code": response.status_code,
                "data": response_data,
                "provider": provider,
                "endpoint": endpoint,
            }

            # SECURITY: Scrub any accidental key leakage in response
            result_str = json.dumps(result)
            scrubbed = self._scrub_secrets(result_str, provider)
            if scrubbed != result_str:
                audit_logger.warning(
                    f"KEY_LEAK_SCRUBBED | provider={provider} | "
                    f"endpoint={endpoint}"
                )
                result = json.loads(scrubbed)

            audit_logger.info(
                f"PROXY_RESPONSE | provider={provider} | "
                f"status={response.status_code}"
            )

            return result

        except requests.RequestException as e:
            # Scrub error message of any key material
            error_msg = self._scrub_secrets(str(e), provider)
            audit_logger.error(
                f"PROXY_ERROR | provider={provider} | error={error_msg}"
            )
            return {
                "status_code": 0,
                "error": error_msg,
                "provider": provider,
                "endpoint": endpoint,
            }

    def check_provider(self, provider: str) -> dict:
        """
        Check if a provider is configured and has a stored key.
        Returns status (never the key).
        """
        config = PROVIDER_AUTH_CONFIG.get(provider)
        if not config:
            return {
                "provider": provider,
                "configured": False,
                "reason": "Unknown provider"
            }

        try:
            # Just check if key exists — get_key is internal
            self.vault.get_key(provider)
            has_key = True
        except VaultError:
            has_key = False

        return {
            "provider": provider,
            "configured": True,
            "has_key": has_key,
            "base_url": config["base_url"],
            "auth_method": config["auth_method"],
        }

    def list_supported_providers(self) -> dict:
        """List all supported provider configurations."""
        result = {}
        for name, config in PROVIDER_AUTH_CONFIG.items():
            result[name] = {
                "base_url": config["base_url"],
                "auth_method": config["auth_method"],
            }
        return {"supported_providers": result}
