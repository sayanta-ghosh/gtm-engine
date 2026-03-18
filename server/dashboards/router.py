"""Dashboards router: CRUD operations for tenant dashboards."""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.auth.models import Tenant
from server.core.config import settings
from server.core.database import get_db, set_tenant_context
from server.dashboards.models import Dashboard
from server.dashboards.schemas import (
    CreateDashboardRequest,
    DashboardListResponse,
    DashboardResponse,
    UpdateDashboardRequest,
)
from server.dashboards.service import (
    build_default_config,
    generate_read_token,
    hash_password,
)
from server.data.dataset_models import Dataset

router = APIRouter(prefix="/api/v1", tags=["dashboards"])

_COOKIE_NAME = "nrv_session"


async def _get_tenant_flexible(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> tuple[Tenant, AsyncSession]:
    """Authenticate via Bearer token, session cookie, or query param."""
    jwt_token: str | None = None

    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        jwt_token = auth_header.removeprefix("Bearer ")

    if not jwt_token:
        jwt_token = request.cookies.get(_COOKIE_NAME)

    if not jwt_token and token:
        jwt_token = token

    if not jwt_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    try:
        payload = jwt.decode(
            jwt_token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please sign in again.",
        )

    tenant_id: str | None = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token: missing tenant_id",
        )

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    await set_tenant_context(db, tenant.id)
    return tenant, db


def _dashboard_to_response(
    d: Dashboard,
    *,
    dataset_name: str | None = None,
    read_token: str | None = None,
) -> DashboardResponse:
    """Map a Dashboard ORM object to a DashboardResponse."""
    config = d.config or {}
    widgets = config.get("widgets", [])
    return DashboardResponse(
        id=str(d.id),
        tenant_id=d.tenant_id,
        name=d.name,
        dataset_id=str(d.dataset_id) if d.dataset_id else None,
        dataset_name=dataset_name,
        config=config,
        widget_count=len(widgets),
        status=d.status,
        refresh_interval=d.refresh_interval,
        read_token=read_token,
        created_at=d.created_at,
        updated_at=d.updated_at,
    )


@router.get("/dashboards", response_model=DashboardListResponse)
async def list_dashboards(
    deps: tuple = Depends(_get_tenant_flexible),
) -> DashboardListResponse:
    """List all dashboards for the current tenant."""
    tenant, db = deps

    result = await db.execute(
        select(Dashboard).where(Dashboard.tenant_id == tenant.id)
    )
    dashboards = result.scalars().all()

    dataset_ids = [d.dataset_id for d in dashboards if d.dataset_id]
    ds_names: dict[str, str] = {}
    if dataset_ids:
        ds_result = await db.execute(
            select(Dataset).where(Dataset.id.in_(dataset_ids))
        )
        for ds in ds_result.scalars().all():
            ds_names[str(ds.id)] = ds.name

    return DashboardListResponse(
        dashboards=[
            _dashboard_to_response(
                d,
                dataset_name=ds_names.get(str(d.dataset_id)) if d.dataset_id else None,
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
    deps: tuple = Depends(_get_tenant_flexible),
) -> DashboardResponse:
    """Create a new dashboard backed by a dataset."""
    tenant, db = deps

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

    ds_result = await db.execute(
        select(Dataset).where(
            Dataset.id == UUID(body.dataset_id),
            Dataset.tenant_id == tenant.id,
        )
    )
    dataset = ds_result.scalar_one_or_none()
    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Dataset not found",
        )

    config = body.config or build_default_config(dataset.columns or [])
    raw_token, token_hash = generate_read_token()
    pwd_hash = hash_password(body.password) if body.password else None

    dashboard = Dashboard(
        tenant_id=tenant.id,
        name=body.name,
        dataset_id=dataset.id,
        config=config,
        s3_path=None,
        data_queries=None,
        read_token_hash=token_hash,
        read_token=raw_token,
        refresh_interval=body.refresh_interval,
        password_hash=pwd_hash,
    )
    db.add(dashboard)
    await db.commit()
    await db.refresh(dashboard)

    return _dashboard_to_response(
        dashboard,
        dataset_name=dataset.name,
        read_token=raw_token,
    )


@router.put("/dashboards/{dashboard_id}", response_model=DashboardResponse)
async def update_dashboard(
    dashboard_id: str,
    body: UpdateDashboardRequest,
    deps: tuple = Depends(_get_tenant_flexible),
) -> DashboardResponse:
    """Update a dashboard's config, name, or password."""
    tenant, db = deps

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

    if body.name is not None:
        dashboard.name = body.name
    if body.config is not None:
        dashboard.config = body.config
    if body.refresh_interval is not None:
        dashboard.refresh_interval = body.refresh_interval
    if body.password is not None:
        dashboard.password_hash = hash_password(body.password)

    await db.commit()
    await db.refresh(dashboard)

    ds_name = None
    if dashboard.dataset_id:
        ds = await db.execute(
            select(Dataset).where(Dataset.id == dashboard.dataset_id)
        )
        ds_obj = ds.scalar_one_or_none()
        ds_name = ds_obj.name if ds_obj else None

    return _dashboard_to_response(dashboard, dataset_name=ds_name)


@router.delete("/dashboards/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(
    dashboard_id: str,
    deps: tuple = Depends(_get_tenant_flexible),
) -> None:
    """Delete a dashboard."""
    tenant, db = deps

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
