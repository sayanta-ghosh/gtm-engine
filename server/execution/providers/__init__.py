"""Provider registry for the execution engine."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from server.execution.providers.base import BaseProvider

# Provider registry - populated by provider modules
_registry: dict[str, type["BaseProvider"]] = {}


def register_provider(name: str, provider_cls: type["BaseProvider"]) -> None:
    """Register a provider class under the given name."""
    _registry[name] = provider_cls


def get_provider(name: str) -> type["BaseProvider"] | None:
    """Look up a registered provider by name."""
    return _registry.get(name)


def list_providers() -> list[str]:
    """Return the names of all registered providers."""
    return list(_registry.keys())
