"""Backward compatibility re-exports for vault models.

New code should import from server.vault.models.
"""

from server.vault.models import TenantKey

__all__ = ["TenantKey"]
