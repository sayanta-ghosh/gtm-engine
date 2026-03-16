"""Backward compatibility re-export.

New code should import from server.billing.router.
"""

from server.billing.router import router

__all__ = ["router"]
