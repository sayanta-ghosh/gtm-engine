"""Backward compatibility re-exports for data models.

New code should import from server.data.models.
"""

from server.data.models import Company, Contact, SearchResult

__all__ = ["Company", "Contact", "SearchResult"]
