"""Backward compatibility re-export.

New code should import from server.vault.router.
"""

from server.vault.router import router

__all__ = ["router"]
