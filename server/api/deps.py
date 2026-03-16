"""Backward compatibility re-export.

New code should import from server.auth.dependencies.
"""

from server.auth.dependencies import get_current_tenant, get_current_user, require_credits

__all__ = ["get_current_tenant", "get_current_user", "require_credits"]
