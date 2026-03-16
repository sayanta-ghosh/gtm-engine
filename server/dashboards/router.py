"""Dashboards router: CRUD operations for tenant dashboards."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.dependencies import get_current_tenant
from server.auth.models import Tenant
from server.core.database import get_db, set_tenant_context
from server.dashboards.models import Dashboard
from server.dashboards.schemas import (
    CreateDashboardRequest,
    DashboardListResponse,
    DashboardResponse,
)
from server.dashboards.service import deploy_to_s3, generate_read_token, hash_password

router = APIRouter(prefix="/api/v1", tags=["dashboards"])


@router.get("/dashboards", response_model=DashboardListResponse)
async def list_dashboards(
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> DashboardListResponse:
    """List all dashboards for the current tenant."""
    await set_tenant_context(db, tenant.id)

    result = await db.execute(
        select(Dashboard).where(Dashboard.tenant_id == tenant.id)
    )
    dashboards = result.scalars().all()
    return DashboardListResponse(
        dashboards=[
            DashboardResponse(
                id=str(d.id),
                tenant_id=d.tenant_id,
                name=d.name,
                status=d.status,
                refresh_interval=d.refresh_interval,
                created_at=d.created_at,
                updated_at=d.updated_at,
            )
            for d in dashboards
        ],
        total=len(dashboards),
    )


@router.post(
    "/dashboards",
    response_model=DashboardResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_dashboard(
    body: CreateDashboardRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> DashboardResponse:
    """Create and deploy a new dashboard."""
    await set_tenant_context(db, tenant.id)

    # Check for duplicate name
    existing = await db.execute(
        select(Dashboard).where(
            Dashboard.tenant_id == tenant.id,
            Dashboard.name == body.name,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Dashboard '{body.name}' already exists",
        )

    # Deploy to S3
    s3_path = await deploy_to_s3(tenant.id, body.name, body.data_queries)

    # Generate read token
    _raw_token, token_hash = generate_read_token()

    # Hash password if provided
    pwd_hash = hash_password(body.password) if body.password else None

    dashboard = Dashboard(
        tenant_id=tenant.id,
        name=body.name,
        s3_path=s3_path,
        data_queries=body.data_queries,
        read_token_hash=token_hash,
        refresh_interval=body.refresh_interval,
        password_hash=pwd_hash,
    )
    db.add(dashboard)
    await db.commit()
    await db.refresh(dashboard)

    return DashboardResponse(
        id=str(dashboard.id),
        tenant_id=dashboard.tenant_id,
        name=dashboard.name,
        status=dashboard.status,
        refresh_interval=dashboard.refresh_interval,
        created_at=dashboard.created_at,
        updated_at=dashboard.updated_at,
    )


@router.delete("/dashboards/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(
    dashboard_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a dashboard."""
    await set_tenant_context(db, tenant.id)

    result = await db.execute(
        select(Dashboard).where(
            Dashboard.id == dashboard_id,
            Dashboard.tenant_id == tenant.id,
        )
    )
    dashboard = result.scalar_one_or_none()
    if dashboard is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dashboard not found",
        )
    await db.delete(dashboard)
    await db.commit()
