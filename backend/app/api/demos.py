from typing import Any

from fastapi import APIRouter

from app.security.tenant import DEFAULT_TENANT_ID, current_tenant_id
from app.services.demos import import_official_demos, remove_official_demos

router = APIRouter(prefix="/demos", tags=["demos"])


@router.post("/official")
async def import_demos() -> dict[str, Any]:
    tenant_id = current_tenant_id() or DEFAULT_TENANT_ID
    return await import_official_demos(tenant_id)


@router.delete("/official")
async def remove_demos() -> dict[str, int]:
    tenant_id = current_tenant_id() or DEFAULT_TENANT_ID
    return await remove_official_demos(tenant_id)
