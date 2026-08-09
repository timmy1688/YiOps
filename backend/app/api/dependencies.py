from app.security.tenant import DEFAULT_TENANT_ID, current_tenant_id


def tenant_id() -> str:
    """Return the authenticated workspace, falling back only when auth is disabled."""
    return current_tenant_id() or DEFAULT_TENANT_ID
