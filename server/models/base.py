"""Shared SQLAlchemy declarative base.

Re-exports Base from the core module for backward compatibility.
New code should import from server.core.database.
"""

from server.core.database import Base

__all__ = ["Base"]
