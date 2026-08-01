from app.security.auth import AuthenticationMiddleware, hash_password, verify_password
from app.security.tenant import current_tenant_id, tenant_filter, tenant_scope


def test_password_hash_round_trip_and_random_salt() -> None:
    first = hash_password("correct horse battery staple")
    second = hash_password("correct horse battery staple")

    assert first != second
    assert verify_password("correct horse battery staple", first)
    assert not verify_password("wrong password", first)
    assert not verify_password("anything", "not-a-supported-hash")


def test_tenant_scope_is_nested_and_restored() -> None:
    assert current_tenant_id() is None
    assert tenant_filter() == {}

    with tenant_scope("tenant_a"):
        assert tenant_filter() == {"tenant_id": "tenant_a"}
        with tenant_scope("tenant_b"):
            assert current_tenant_id() == "tenant_b"
        assert current_tenant_id() == "tenant_a"

    assert current_tenant_id() is None


def test_only_expected_routes_are_public() -> None:
    assert AuthenticationMiddleware._is_public("/health/ready", "GET")
    assert AuthenticationMiddleware._is_public("/auth/login", "POST")
    assert AuthenticationMiddleware._is_public(
        "/integrations/integration_1/webhook/token", "POST"
    )
    assert AuthenticationMiddleware._is_public("/shared/investigations/token", "GET")
    assert not AuthenticationMiddleware._is_public("/incidents", "GET")
    assert not AuthenticationMiddleware._is_public("/auth/logout", "POST")
