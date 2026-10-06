"""Request-scoped auth accessors — the bridge from middleware to routes.

The ASGI middleware resolves the cookie once per request and stashes an
AuthedUser in request.state. Routes never read cookies themselves; they take
`Depends(get_current_user)` and, for admin surfaces, `Depends(require_admin)`.

Polarity: when auth is ENABLED, a route reached without a middleware-attached
user is a hard 401 (fail closed — this only happens if a route was somehow
mounted outside the middleware). The single local "dev" identity exists only
behind the explicit AUTH_ENABLED=false dev escape hatch, so unit tests and
local development run without an Entra tenant.
"""

from dataclasses import dataclass, field

from fastapi import HTTPException, Request

from ragline.config import settings


@dataclass
class AuthedUser:
    """The signed-in identity, as routes and the ACL check consume it."""

    oid: str
    upn: str = ""
    display_name: str = ""
    groups: list[str] = field(default_factory=list)
    groups_overage: bool = False
    session_id: str = ""

    @property
    def is_admin(self) -> bool:
        gid = settings.entra_admin_group_id
        return bool(gid) and gid in self.groups


# The identity every request assumes when AUTH_ENABLED=false (dev only).
DEV_USER = AuthedUser(oid="dev-local", upn="dev@localhost", display_name="Dev (auth disabled)")


def get_current_user(request: Request) -> AuthedUser:
    user = getattr(request.state, "user", None)
    if user is not None:
        return user
    if not settings.auth_enabled:
        return DEV_USER
    raise HTTPException(status_code=401, detail="Not authenticated")


def require_admin(request: Request) -> AuthedUser:
    user = get_current_user(request)
    if not settings.auth_enabled:
        # Dev escape hatch: admin surfaces are reachable locally.
        return user
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin group membership required")
    return user
