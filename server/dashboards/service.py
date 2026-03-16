"""Dashboard service: build, deploy to S3, manage dashboards.

Stub implementation - S3 deployment will be added when AWS infrastructure
is provisioned.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import Any


def generate_read_token() -> tuple[str, str]:
    """Generate a read token and its hash.

    Returns (raw_token, token_hash).
    """
    raw = secrets.token_urlsafe(32)
    hashed = hashlib.sha256(raw.encode()).hexdigest()
    return raw, hashed


def hash_password(password: str) -> str:
    """Hash a dashboard access password."""
    return hashlib.sha256(password.encode()).hexdigest()


async def deploy_to_s3(
    tenant_id: str,
    dashboard_name: str,
    data_queries: dict[str, Any] | None,
) -> str:
    """Deploy a dashboard to S3 and return the S3 path.

    Stub implementation - returns a mock path.
    """
    # Real implementation would:
    # 1. Render the dashboard template
    # 2. Upload to S3 bucket
    # 3. Return the S3 key
    return f"dashboards/{tenant_id}/{dashboard_name}/index.html"
