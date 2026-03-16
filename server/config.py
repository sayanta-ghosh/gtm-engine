"""Backward compatibility re-export.

New code should import from server.core.config.
"""

from server.core.config import Settings, settings

__all__ = ["Settings", "settings"]
