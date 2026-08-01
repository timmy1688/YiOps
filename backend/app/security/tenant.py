from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token

DEFAULT_TENANT_ID = "tenant_default"

_tenant_id: ContextVar[str | None] = ContextVar("yiops_tenant_id", default=None)


def current_tenant_id() -> str | None:
    return _tenant_id.get()


def set_tenant_id(tenant_id: str) -> Token[str | None]:
    return _tenant_id.set(tenant_id)


def reset_tenant_id(token: Token[str | None]) -> None:
    _tenant_id.reset(token)


@contextmanager
def tenant_scope(tenant_id: str) -> Iterator[None]:
    token = set_tenant_id(tenant_id)
    try:
        yield
    finally:
        reset_tenant_id(token)


def tenant_filter() -> dict[str, str]:
    tenant_id = current_tenant_id()
    return {"tenant_id": tenant_id} if tenant_id else {}
