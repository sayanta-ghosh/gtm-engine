"""Execution persistence — log every call, store enriched records.

After every execution (success or failure), the pipeline writes:

1. **EnrichmentLog** — Immutable audit trail of every API call.
   Captures: provider, operation, params, result, status, cost, latency, cached.
   Used for: billing reconciliation, debugging, provider analytics.

2. **Contact / Company** — Upsert enriched records into the tenant's tables.
   On conflict (same email / same domain): merge new fields into existing record,
   preserving data the tenant already has. Tracks enrichment_sources per field.

3. **SearchResult** — Cache search results for de-duplication and history.
   Allows the UI/CLI to show "you searched for this before" and avoid re-running.

This module is called by the execution router AFTER a successful execution.
It never blocks or fails the main response — if persistence fails, we log
and continue (the user still gets their data).
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.data.models import Contact, Company, EnrichmentLog, SearchResult

logger = logging.getLogger(__name__)

# Operations that produce person data
PERSON_OPERATIONS = {"enrich_person", "search_people", "bulk_enrich_people"}
# Operations that produce company data
COMPANY_OPERATIONS = {"enrich_company", "search_companies", "bulk_enrich_companies"}
# Operations that are searches (log to search_results)
SEARCH_OPERATIONS = {"search_people", "search_companies"}


# ---------------------------------------------------------------------------
# Enrichment log (every call, success or failure)
# ---------------------------------------------------------------------------


async def log_execution(
    db: AsyncSession,
    *,
    tenant_id: str,
    execution_id: str,
    batch_id: str | None = None,
    operation: str,
    provider: str,
    key_mode: str,  # "platform" | "byok"
    params: dict[str, Any],
    result: dict[str, Any] | None = None,
    status: str,  # "success" | "failed" | "cached"
    error_message: str | None = None,
    credits_charged: float = 0.0,
    duration_ms: int | None = None,
    cached: bool = False,
) -> None:
    """Write an immutable audit record of an execution.

    This is called for EVERY execution — success, failure, and cache hit.
    Never raises — if logging fails, we log the error and continue.
    """
    try:
        entry = EnrichmentLog(
            tenant_id=tenant_id,
            execution_id=execution_id,
            batch_id=batch_id,
            operation=operation,
            provider=provider,
            key_mode=key_mode,
            params=params,
            result=result,
            status=status,
            error_message=error_message,
            credits_charged=credits_charged,
            duration_ms=duration_ms,
            cached=cached,
        )
        db.add(entry)
        await db.flush()
        logger.debug(
            "Logged execution %s: %s/%s status=%s cost=%.2f",
            execution_id, provider, operation, status, credits_charged,
        )
    except Exception:
        logger.warning("Failed to log execution %s", execution_id, exc_info=True)


# ---------------------------------------------------------------------------
# Contact upsert (enrich_person results)
# ---------------------------------------------------------------------------

# Fields on the Contact model that can be enriched
_CONTACT_FIELDS = {
    "email", "name", "first_name", "last_name", "title", "phone",
    "linkedin", "company", "company_domain", "location",
}


async def upsert_contact(
    db: AsyncSession,
    tenant_id: str,
    data: dict[str, Any],
    provider: str,
) -> None:
    """Insert or update a contact from enrichment data.

    Merge strategy: only overwrite fields that are currently NULL on the
    existing record. This preserves user-edited data while filling gaps
    with enrichment data. Tracks enrichment_sources per provider.

    If no email is present, the contact cannot be upserted (email is the
    dedup key for contacts).
    """
    email = data.get("email")
    if not email:
        return  # Can't upsert without an email (the dedup key)

    try:
        # Check if contact already exists for this tenant
        result = await db.execute(
            select(Contact).where(
                Contact.tenant_id == tenant_id,
                Contact.email == email,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            # Insert new contact
            contact = Contact(
                tenant_id=tenant_id,
                email=email,
                enrichment_sources=data.get("enrichment_sources", {provider: ["person"]}),
            )
            for field in _CONTACT_FIELDS:
                if field in data and data[field] is not None:
                    setattr(contact, field, data[field])
            db.add(contact)
        else:
            # Merge: fill NULL fields with new data
            updated = False
            for field in _CONTACT_FIELDS:
                current_val = getattr(existing, field, None)
                new_val = data.get(field)
                if current_val is None and new_val is not None:
                    setattr(existing, field, new_val)
                    updated = True

            # Merge enrichment_sources
            sources = dict(existing.enrichment_sources or {})
            new_sources = data.get("enrichment_sources", {})
            for src_provider, src_fields in new_sources.items():
                if src_provider not in sources:
                    sources[src_provider] = src_fields
                else:
                    # Merge field lists
                    existing_fields = set(sources[src_provider])
                    existing_fields.update(src_fields)
                    sources[src_provider] = list(existing_fields)
            if sources != existing.enrichment_sources:
                existing.enrichment_sources = sources
                updated = True

            if updated:
                logger.debug("Updated contact %s with data from %s", email, provider)

        await db.flush()
    except Exception:
        logger.warning("Failed to upsert contact %s", email, exc_info=True)


# ---------------------------------------------------------------------------
# Company upsert (enrich_company results)
# ---------------------------------------------------------------------------

# Fields on the Company model that can be enriched
_COMPANY_FIELDS = {
    "domain", "name", "industry", "employee_count", "employee_range",
    "revenue_range", "funding_stage", "total_funding", "location",
    "description",
}


async def upsert_company(
    db: AsyncSession,
    tenant_id: str,
    data: dict[str, Any],
    provider: str,
) -> None:
    """Insert or update a company from enrichment data.

    Same merge strategy as contacts: only fill NULL fields.
    Domain is the dedup key for companies.
    """
    domain = data.get("domain") or data.get("company_domain")
    if not domain:
        return  # Can't upsert without a domain

    try:
        result = await db.execute(
            select(Company).where(
                Company.tenant_id == tenant_id,
                Company.domain == domain,
            )
        )
        existing = result.scalar_one_or_none()

        if existing is None:
            company = Company(
                tenant_id=tenant_id,
                domain=domain,
                enrichment_sources=data.get("enrichment_sources", {provider: ["company"]}),
            )
            for field in _COMPANY_FIELDS:
                if field in data and data[field] is not None:
                    setattr(company, field, data[field])

            # Handle technologies (array field)
            if data.get("technologies"):
                company.technologies = data["technologies"]

            db.add(company)
        else:
            updated = False
            for field in _COMPANY_FIELDS:
                current_val = getattr(existing, field, None)
                new_val = data.get(field)
                if current_val is None and new_val is not None:
                    setattr(existing, field, new_val)
                    updated = True

            # Merge technologies
            if data.get("technologies") and not existing.technologies:
                existing.technologies = data["technologies"]
                updated = True

            # Merge enrichment_sources
            sources = dict(existing.enrichment_sources or {})
            new_sources = data.get("enrichment_sources", {})
            for src_provider, src_fields in new_sources.items():
                if src_provider not in sources:
                    sources[src_provider] = src_fields
                else:
                    existing_fields = set(sources[src_provider])
                    existing_fields.update(src_fields)
                    sources[src_provider] = list(existing_fields)
            if sources != existing.enrichment_sources:
                existing.enrichment_sources = sources
                updated = True

            if updated:
                logger.debug("Updated company %s with data from %s", domain, provider)

        await db.flush()
    except Exception:
        logger.warning("Failed to upsert company %s", domain, exc_info=True)


# ---------------------------------------------------------------------------
# Search result caching
# ---------------------------------------------------------------------------


async def save_search_result(
    db: AsyncSession,
    tenant_id: str,
    operation: str,
    params: dict[str, Any],
    results: dict[str, Any],
) -> None:
    """Save a search result for history and de-duplication."""
    try:
        params_json = json.dumps(params, sort_keys=True)
        query_hash = hashlib.sha256(
            f"{operation}:{params_json}".encode()
        ).hexdigest()[:16]

        # Count results
        result_count = 0
        if "people" in results:
            result_count = len(results.get("people", []))
        elif "companies" in results:
            result_count = len(results.get("companies", []))

        entry = SearchResult(
            tenant_id=tenant_id,
            query_hash=query_hash,
            operation=operation,
            params=params,
            result_count=result_count,
            results=results,
        )
        db.add(entry)
        await db.flush()
    except Exception:
        logger.warning("Failed to save search result", exc_info=True)


# ---------------------------------------------------------------------------
# Main persistence entry point (called after execution)
# ---------------------------------------------------------------------------


async def persist_execution(
    db: AsyncSession,
    *,
    tenant_id: str,
    execution_id: str,
    batch_id: str | None = None,
    operation: str,
    provider: str,
    is_byok: bool,
    params: dict[str, Any],
    result_data: dict[str, Any] | None,
    status: str,  # "success" | "failed" | "cached"
    error_message: str | None = None,
    credits_charged: float = 0.0,
    duration_ms: int | None = None,
    cached: bool = False,
) -> None:
    """One-call persistence: log + upsert records + cache searches.

    This is the single entry point called by the router after every execution.
    It handles all persistence in one place and never raises.
    """
    # 1. Always log the execution
    await log_execution(
        db,
        tenant_id=tenant_id,
        execution_id=execution_id,
        batch_id=batch_id,
        operation=operation,
        provider=provider,
        key_mode="byok" if is_byok else "platform",
        params=params,
        result=result_data,
        status=status,
        error_message=error_message,
        credits_charged=credits_charged,
        duration_ms=duration_ms,
        cached=cached,
    )

    # 2. On success, upsert enriched records
    if status in ("success", "cached") and result_data:
        if operation in PERSON_OPERATIONS:
            # Single person enrichment
            if operation == "enrich_person" and "people" not in result_data:
                await upsert_contact(db, tenant_id, result_data, provider)
            # Search or bulk: upsert each person in the list
            elif "people" in result_data:
                for person in result_data.get("people", []):
                    await upsert_contact(db, tenant_id, person, provider)

        elif operation in COMPANY_OPERATIONS:
            # Single company enrichment
            if operation == "enrich_company" and "companies" not in result_data:
                await upsert_company(db, tenant_id, result_data, provider)
            # Search or bulk: upsert each company
            elif "companies" in result_data:
                for company in result_data.get("companies", []):
                    await upsert_company(db, tenant_id, company, provider)

        # 3. Cache search results
        if operation in SEARCH_OPERATIONS:
            await save_search_result(db, tenant_id, operation, params, result_data)

    try:
        await db.commit()
    except Exception:
        logger.warning("Failed to commit persistence for %s", execution_id, exc_info=True)
        await db.rollback()
