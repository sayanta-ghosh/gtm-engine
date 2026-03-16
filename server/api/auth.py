"""Backward compatibility re-export.

New code should import from server.auth.router.
"""

from server.auth.router import router

__all__ = ["router"]
