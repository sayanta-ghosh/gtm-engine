"""Apps API router: deploy, list, and manage hosted apps."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from jose import JWTError, jwt
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from server.apps import service as svc
from server.apps.models import HostedApp
from server.auth.models import Tenant
from server.core.config import settings
from server.core.database import get_db, set_tenant_context

router = APIRouter(prefix="/api/v1", tags=["apps"])

_COOKIE_NAME = "nrv_session"


# ---- Auth (same flex pattern) ----

async def _get_tenant_flexible(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> tuple[Tenant, AsyncSession]:
    """Authenticate via Bearer, cookie, or query param."""
    jwt_token: str | None = None
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        jwt_token = auth_header.removeprefix("Bearer ")
    if not jwt_token:
        jwt_token = request.cookies.get(_COOKIE_NAME)
    if not jwt_token and token:
        jwt_token = token
    if not jwt_token:
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        payload = jwt.decode(jwt_token, settings.JWT_SECRET_KEY, algorithms=["HS256"])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    tenant_id = payload.get("tenant_id")
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id")

    result = await db.execute(select(Tenant).where(Tenant.id == tenant_id))
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise HTTPException(status_code=401, detail="Tenant not found")

    await set_tenant_context(db, tenant.id)
    return tenant, db


# ---- Request models ----

class DeployAppRequest(BaseModel):
    name: str
    files: dict[str, str]  # {path: content}
    dataset_ids: list[str]
    entry_point: str = "index.html"


# ---- Endpoints ----

@router.post("/apps")
async def deploy_app(
    body: DeployAppRequest,
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Deploy a static app backed by datasets."""
    tenant, db = await _get_tenant_flexible(request, token, db)

    if not body.files:
        raise HTTPException(status_code=400, detail="No files provided")
    if body.entry_point not in body.files:
        raise HTTPException(
            status_code=400,
            detail=f"Entry point '{body.entry_point}' not found in files",
        )

    result = await svc.deploy_app(
        db,
        tenant.id,
        body.name,
        body.files,
        body.dataset_ids,
        body.entry_point,
    )
    return result


@router.get("/apps")
async def list_apps(
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """List all deployed apps."""
    tenant, db = await _get_tenant_flexible(request, token, db)
    apps = await svc.list_apps(db, tenant.id)
    return {"apps": apps, "total": len(apps)}


@router.delete("/apps/{app_id}", status_code=204)
async def delete_app(
    app_id: str,
    request: Request,
    token: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Delete a hosted app."""
    tenant, db = await _get_tenant_flexible(request, token, db)
    deleted = await svc.delete_app(db, tenant.id, app_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="App not found")


# ---- App serving (public, no auth) ----

@router.get("/apps/{app_token}/{path:path}", include_in_schema=False)
async def serve_app_file(
    app_token: str,
    path: str = "",
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Serve a static file from a hosted app. Public — no auth needed."""
    app = await svc.get_app_by_token(db, app_token)
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    # Default to entry point
    if not path or path == "/":
        path = app.entry_point or "index.html"

    files = app.files or {}
    if path not in files:
        # Try without leading slash
        path = path.lstrip("/")
        if path not in files:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

    content = files[path]
    content_type = svc.get_content_type(path)

    # Inject NRV context into HTML files
    if content_type == "text/html":
        api_base = "/api/v1"
        content = svc.inject_nrv_context(content, app.app_token, api_base)
        return HTMLResponse(content=content)

    return Response(content=content, media_type=content_type)
