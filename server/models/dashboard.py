"""Backward compatibility re-exports for dashboard models.

New code should import from server.dashboards.models.
"""

from server.dashboards.models import Dashboard

__all__ = ["Dashboard"]
