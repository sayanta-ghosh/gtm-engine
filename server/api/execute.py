"""Backward compatibility re-export.

New code should import from server.execution.router.
"""

from server.execution.router import router

__all__ = ["router"]
