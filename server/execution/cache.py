"""Redis response cache for provider API calls."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import redis.asyncio as aioredis


class ResponseCache:
    """Redis-backed cache for provider responses.

    Keys are derived from the operation + params hash, scoped per tenant.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        default_ttl: int = 3600,  # 1 hour
        prefix: str = "cache:exec",
    ) -> None:
        self.redis = redis
        self.default_ttl = default_ttl
        self.prefix = prefix

    def _cache_key(self, tenant_id: str, operation: str, params: dict[str, Any]) -> str:
        """Build a deterministic cache key from the operation and params."""
        params_json = json.dumps(params, sort_keys=True)
        digest = hashlib.sha256(f"{operation}:{params_json}".encode()).hexdigest()[:16]
        return f"{self.prefix}:{tenant_id}:{operation}:{digest}"

    async def get(
        self, tenant_id: str, operation: str, params: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Look up a cached response. Returns None on cache miss."""
        key = self._cache_key(tenant_id, operation, params)
        raw = await self.redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)

    async def set(
        self,
        tenant_id: str,
        operation: str,
        params: dict[str, Any],
        result: dict[str, Any],
        ttl: int | None = None,
    ) -> None:
        """Store a response in the cache."""
        key = self._cache_key(tenant_id, operation, params)
        await self.redis.set(
            key,
            json.dumps(result),
            ex=ttl or self.default_ttl,
        )

    async def invalidate(
        self, tenant_id: str, operation: str, params: dict[str, Any]
    ) -> None:
        """Remove a cached response."""
        key = self._cache_key(tenant_id, operation, params)
        await self.redis.delete(key)
