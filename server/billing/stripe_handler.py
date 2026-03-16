"""Stripe integration: checkout session creation and webhook handling."""

from __future__ import annotations

from typing import Any

from server.core.config import settings

# Credit packages
PACKAGES: dict[str, dict[str, Any]] = {
    "starter": {"credits": 100, "price_cents": 999, "name": "Starter (100 credits)"},
    "growth": {"credits": 500, "price_cents": 3999, "name": "Growth (500 credits)"},
    "scale": {"credits": 2000, "price_cents": 12999, "name": "Scale (2000 credits)"},
}


async def create_checkout_session(
    tenant_id: str,
    package: str,
    success_url: str | None = None,
    cancel_url: str | None = None,
) -> dict[str, str]:
    """Create a Stripe Checkout session for a credit package.

    Returns a dict with ``checkout_url`` and ``session_id``.

    Stub implementation - returns mock data when STRIPE_SECRET_KEY is not set.
    """
    if not settings.STRIPE_SECRET_KEY:
        return {
            "checkout_url": f"https://checkout.stripe.com/mock/{package}",
            "session_id": f"cs_mock_{package}",
        }

    # Real Stripe integration would go here:
    # import stripe
    # stripe.api_key = settings.STRIPE_SECRET_KEY
    # session = stripe.checkout.Session.create(...)
    # return {"checkout_url": session.url, "session_id": session.id}

    raise NotImplementedError("Stripe integration not yet implemented")


async def handle_webhook(payload: bytes, sig_header: str) -> dict[str, Any]:
    """Process a Stripe webhook event.

    Stub implementation - will verify the signature and handle
    checkout.session.completed events to credit the tenant.
    """
    if not settings.STRIPE_WEBHOOK_SECRET:
        return {"status": "ignored", "reason": "webhook secret not configured"}

    # Real implementation:
    # import stripe
    # event = stripe.Webhook.construct_event(payload, sig_header, settings.STRIPE_WEBHOOK_SECRET)
    # if event["type"] == "checkout.session.completed": ...

    raise NotImplementedError("Stripe webhook handling not yet implemented")
