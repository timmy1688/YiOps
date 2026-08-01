import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from time import monotonic

from fastapi import APIRouter, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import Settings, get_settings
from app.models import Tenant, User, UserSession, new_id
from app.schemas import AuthStatusRead, CurrentUserRead, LoginRequest, PasswordChangeRequest
from app.security.tenant import DEFAULT_TENANT_ID, reset_tenant_id, set_tenant_id

SESSION_COOKIE = "yiops_session"
CSRF_COOKIE = "yiops_csrf"
CSRF_HEADER = "X-YiOps-CSRF"
_PASSWORD_N = 2**14
_PASSWORD_R = 8
_PASSWORD_P = 1
_LOGIN_WINDOW_SECONDS = 300
_LOGIN_MAX_ATTEMPTS = 5
_login_attempts: dict[str, list[float]] = {}

router = APIRouter(prefix="/auth", tags=["auth"])


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(
        password.encode(),
        salt=salt,
        n=_PASSWORD_N,
        r=_PASSWORD_R,
        p=_PASSWORD_P,
        dklen=32,
    )
    return f"scrypt${_PASSWORD_N}${_PASSWORD_R}${_PASSWORD_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_n, raw_r, raw_p, raw_salt, expected = encoded.split("$", 5)
        if algorithm != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(),
            salt=bytes.fromhex(raw_salt),
            n=int(raw_n),
            r=int(raw_r),
            p=int(raw_p),
            dklen=len(bytes.fromhex(expected)),
        )
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


async def ensure_bootstrap_identity(settings: Settings) -> None:
    tenant, _ = await Tenant.get_or_create(
        id=DEFAULT_TENANT_ID,
        defaults={"name": "Default Workspace", "slug": "default", "active": True},
    )
    await UserSession.filter(expires_at__lte=datetime.now(UTC)).delete()
    if not settings.auth_enabled or await User.all().exists():
        return
    password = settings.admin_password
    if len(password) < 12:
        raise RuntimeError(
            "YIOPS_ADMIN_PASSWORD must contain at least 12 characters "
            "when authentication is enabled"
        )
    await User.create(
        id=new_id("user"),
        tenant_id=tenant.id,
        username=settings.admin_username.strip() or "admin",
        display_name="YiOps Administrator",
        password_hash=hash_password(password),
        role="admin",
        active=True,
    )


def _user_read(user: User) -> CurrentUserRead:
    return CurrentUserRead(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        role=user.role,
        tenant_id=user.tenant_id,
        tenant_name=user.tenant.name,
    )


def _set_auth_cookies(response: Response, token: str, csrf_token: str, settings: Settings) -> None:
    max_age = settings.session_ttl_hours * 3600
    common = {
        "max_age": max_age,
        "secure": settings.auth_cookie_secure,
        "samesite": "lax",
        "path": "/",
    }
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, csrf_token, httponly=False, **common)


def _clear_auth_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        path="/",
        secure=settings.auth_cookie_secure,
        samesite="lax",
    )
    response.delete_cookie(
        CSRF_COOKIE,
        path="/",
        secure=settings.auth_cookie_secure,
        samesite="lax",
    )


@router.get("/status", response_model=AuthStatusRead)
async def auth_status(request: Request) -> AuthStatusRead:
    settings = get_settings()
    return AuthStatusRead(
        enabled=settings.auth_enabled,
        authenticated=not settings.auth_enabled or getattr(request.state, "user", None) is not None,
    )


@router.post("/login", response_model=CurrentUserRead)
async def login(payload: LoginRequest, request: Request, response: Response) -> CurrentUserRead:
    settings = get_settings()
    if not settings.auth_enabled:
        raise HTTPException(status_code=409, detail="Authentication is disabled")
    username = payload.username.strip()
    throttle_key = f"{request.client.host if request.client else 'unknown'}:{username.lower()}"
    _check_login_throttle(throttle_key)
    user = await User.get_or_none(username=username).select_related("tenant")
    if user is None or not user.active or not user.tenant.active:
        verify_password(payload.password, hash_password("invalid-login-attempt"))
        _record_login_failure(throttle_key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(payload.password, user.password_hash):
        _record_login_failure(throttle_key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    now = datetime.now(UTC)
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(24)
    await UserSession.create(
        id=new_id("session"),
        user_id=user.id,
        token_hash=_digest(token),
        csrf_token_hash=_digest(csrf_token),
        expires_at=now + timedelta(hours=settings.session_ttl_hours),
        last_seen_at=now,
    )
    user.last_login_at = now
    await user.save(update_fields=["last_login_at", "updated_at"])
    _login_attempts.pop(throttle_key, None)
    _set_auth_cookies(response, token, csrf_token, settings)
    request.state.user = user
    return _user_read(user)


@router.get("/me", response_model=CurrentUserRead)
async def me(request: Request) -> CurrentUserRead:
    user = getattr(request.state, "user", None)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return _user_read(user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await UserSession.filter(token_hash=_digest(token)).delete()
    _clear_auth_cookies(response, get_settings())
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.post("/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_password(payload: PasswordChangeRequest, request: Request) -> Response:
    user = getattr(request.state, "user", None)
    session = getattr(request.state, "session", None)
    if user is None or session is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=422, detail="当前密码不正确")
    if hmac.compare_digest(payload.current_password, payload.new_password):
        raise HTTPException(status_code=422, detail="新密码不能与当前密码相同")
    user.password_hash = hash_password(payload.new_password)
    await user.save(update_fields=["password_hash", "updated_at"])
    await UserSession.filter(user_id=user.id).exclude(id=session.id).delete()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _check_login_throttle(key: str) -> None:
    cutoff = monotonic() - _LOGIN_WINDOW_SECONDS
    attempts = [value for value in _login_attempts.get(key, []) if value >= cutoff]
    _login_attempts[key] = attempts
    if len(attempts) >= _LOGIN_MAX_ATTEMPTS:
        raise HTTPException(status_code=429, detail="登录尝试过多，请稍后再试")


def _record_login_failure(key: str) -> None:
    _login_attempts.setdefault(key, []).append(monotonic())


class AuthenticationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.settings = settings

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith(self.settings.api_prefix):
            return await call_next(request)

        path = request.url.path.removeprefix(self.settings.api_prefix)
        if not self.settings.auth_enabled:
            token = set_tenant_id(DEFAULT_TENANT_ID)
            try:
                return await call_next(request)
            finally:
                reset_tenant_id(token)

        public = self._is_public(path, request.method)
        session = await self._session(request)
        if session is not None:
            request.state.user = session.user
            request.state.session = session
        elif not public:
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

        if session is not None and request.method not in {"GET", "HEAD", "OPTIONS"}:
            is_integration_webhook = path.startswith("/integrations/") and "/webhook/" in path
            if path != "/auth/login" and not is_integration_webhook:
                csrf = request.headers.get(CSRF_HEADER, "")
                cookie_csrf = request.cookies.get(CSRF_COOKIE, "")
                if not csrf or not hmac.compare_digest(csrf, cookie_csrf):
                    return JSONResponse(status_code=403, content={"detail": "Invalid CSRF token"})
                if not hmac.compare_digest(_digest(csrf), session.csrf_token_hash):
                    return JSONResponse(status_code=403, content={"detail": "Invalid CSRF token"})

        tenant_id = session.user.tenant_id if session is not None else DEFAULT_TENANT_ID
        tenant_token = set_tenant_id(tenant_id)
        try:
            return await call_next(request)
        finally:
            reset_tenant_id(tenant_token)

    async def _session(self, request: Request) -> UserSession | None:
        raw_token = request.cookies.get(SESSION_COOKIE)
        if not raw_token:
            return None
        session = await UserSession.get_or_none(token_hash=_digest(raw_token)).select_related(
            "user", "user__tenant"
        )
        now = datetime.now(UTC)
        if session is None:
            return None
        if session.expires_at <= now or not session.user.active or not session.user.tenant.active:
            await session.delete()
            return None
        if (now - session.last_seen_at).total_seconds() >= 300:
            session.last_seen_at = now
            await session.save(update_fields=["last_seen_at"])
        return session

    @staticmethod
    def _is_public(path: str, method: str) -> bool:
        if path in {"/health", "/health/live", "/health/ready", "/auth/status"}:
            return True
        if path == "/auth/login" and method == "POST":
            return True
        if path == "/webhooks/alertmanager" and method == "POST":
            return True
        if path.startswith("/integrations/") and "/webhook/" in path and method == "POST":
            return True
        return path.startswith("/shared/investigations/") and method == "GET"
