"""Backward compatibility re-export.

New code should import from server.auth.service.
"""

from server.auth.service import find_or_create_user, generate_tokens, google_exchange_code

__all__ = ["find_or_create_user", "generate_tokens", "google_exchange_code"]
