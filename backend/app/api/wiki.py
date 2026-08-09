from typing import Any

from fastapi import APIRouter, HTTPException, status
from tortoise.exceptions import IntegrityError

from app.config import get_settings
from app.memory.wiki import WikiMemory
from app.models import WikiDocument, new_id
from app.schemas import (
    WikiDocumentCreate,
    WikiDocumentRead,
    WikiDocumentUpdate,
    WikiSearchRequest,
    WikiSearchResult,
)
from app.security.tenant import DEFAULT_TENANT_ID, current_tenant_id

router = APIRouter(prefix="/wiki", tags=["wiki"])
memory = WikiMemory(get_settings())


def _tenant_id() -> str:
    return str(current_tenant_id() or DEFAULT_TENANT_ID)


@router.get("", response_model=list[WikiDocumentRead])
async def list_documents() -> list[WikiDocumentRead]:
    items = await WikiDocument.filter(tenant_id=_tenant_id()).order_by("-updated_at")
    return [WikiDocumentRead.model_validate(item) for item in items]


@router.post("", response_model=WikiDocumentRead, status_code=status.HTTP_201_CREATED)
async def create_document(payload: WikiDocumentCreate) -> WikiDocumentRead:
    try:
        item = await WikiDocument.create(
            id=new_id("wiki"),
            tenant_id=_tenant_id(),
            title=payload.title.strip(),
            content=payload.content.strip(),
            tags=_clean_tags(payload.tags),
            status=payload.status,
        )
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Wiki 标题已存在") from exc
    await memory.reindex(item)
    return WikiDocumentRead.model_validate(item)


@router.get("/{document_id}", response_model=WikiDocumentRead)
async def get_document(document_id: str) -> WikiDocumentRead:
    return WikiDocumentRead.model_validate(await _get(document_id))


@router.patch("/{document_id}", response_model=WikiDocumentRead)
async def update_document(
    document_id: str,
    payload: WikiDocumentUpdate,
) -> WikiDocumentRead:
    item = await _get(document_id)
    updates: dict[str, Any] = payload.model_dump(exclude_unset=True)
    if "title" in updates:
        updates["title"] = str(updates["title"]).strip()
    if "content" in updates:
        updates["content"] = str(updates["content"]).strip()
    if "tags" in updates:
        updates["tags"] = _clean_tags(updates["tags"])
    changed_content = bool({"title", "content", "tags", "status"} & updates.keys())
    for key, value in updates.items():
        setattr(item, key, value)
    if changed_content:
        item.version += 1
    try:
        await item.save()
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Wiki 标题已存在") from exc
    if changed_content:
        await memory.reindex(item)
    return WikiDocumentRead.model_validate(item)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: str) -> None:
    await (await _get(document_id)).delete()


@router.post("/{document_id}/reindex", response_model=WikiDocumentRead)
async def reindex_document(document_id: str) -> WikiDocumentRead:
    item = await _get(document_id)
    await memory.reindex(item)
    return WikiDocumentRead.model_validate(item)


@router.post("/search/query", response_model=list[WikiSearchResult])
async def search_documents(payload: WikiSearchRequest) -> list[WikiSearchResult]:
    return [
        WikiSearchResult.model_validate(item.public_dict())
        for item in await memory.retrieve(payload.query, limit=payload.limit)
    ]


async def _get(document_id: str) -> WikiDocument:
    item = await WikiDocument.get_or_none(id=document_id, tenant_id=_tenant_id())
    if item is None:
        raise HTTPException(status_code=404, detail="Wiki 文档不存在")
    return item


def _clean_tags(tags: list[object]) -> list[str]:
    return list(dict.fromkeys(str(tag).strip()[:80] for tag in tags if str(tag).strip()))[:30]
