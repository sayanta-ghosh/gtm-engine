"""Redis token-bucket rate limiter for provider API calls."""

from __future__ import annotations

import time

import redis.asyncio as aioredis


class TokenBucketRateLimiter:
    """Token-bucket rate limiter backed by Redis.

    Each provider + tenant combination gets its own bucket.
    """

    def __init__(
        self,
        redis: aioredis.Redis,
        max_tokens: int = 10,
        refill_rate: float = 1.0,  # tokens per second
        prefix: str = "ratelimit",
    ) -> None:
        self.redis = redis
        self.max_tokens = max_tokens
        self.refill_rate = refill_rate
        self.prefix = prefix

    def _key(self, provider: str, tenant_id: str) -> str:
        return f"{self.prefix}:{provider}:{tenant_id}"

    async def acquire(self, provider: str, tenant_id: str) -> bool:
        """Try to acquire a token. Returns True if allowed, False if rate-limited."""
        key = self._key(provider, tenant_id)
        now = time.time()

        # Use a Lua script for atomicity
        lua_script = """
        local key = KEYS[1]
        local max_tokens = tonumber(ARGV[1])
        local refill_rate = tonumber(ARGV[2])
        local now = tonumber(ARGV[3])

        local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
        local tokens = tonumber(bucket[1])
        local last_refill = tonumber(bucket[2])

        if tokens == nil then
            tokens = max_tokens
            last_refill = now
        end

        -- Refill tokens
        local elapsed = now - last_refill
        tokens = math.min(max_tokens, tokens + elapsed * refill_rate)
        last_refill = now

        if tokens >= 1 then
            tokens = tokens - 1
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
            redis.call('EXPIRE', key, 3600)
            return 1
        else
            redis.call('HMSET', key, 'tokens', tokens, 'last_refill', last_refill)
            redis.call('EXPIRE', key, 3600)
            return 0
        end
        """
        result = await self.redis.eval(
            lua_script, 1, key, self.max_tokens, self.refill_rate, now
        )
        return bool(result)
