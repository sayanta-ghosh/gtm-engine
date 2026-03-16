"""Backward compatibility re-exports for enrichment models.

New code should import from server.data.models.
"""

from server.data.models import EnrichmentLog

__all__ = ["EnrichmentLog"]
