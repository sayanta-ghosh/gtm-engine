"""Backward compatibility re-export.

New code should import from server.data.router.
"""

from server.data.router import router

__all__ = ["router"]
