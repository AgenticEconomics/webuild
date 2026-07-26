"""Role-Based Access Control middleware.

Roles and their permissions:
- admin:     all permissions
- developer: agent.use, sandbox.create, sandbox.list, session.manage
- viewer:    read-only (agent.use with read scope)
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from webuild_shared.auth_middleware import get_current_user

# Permission matrix: role -> set of allowed actions
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "admin": {
        "user.create",
        "user.list",
        "user.update",
        "user.delete",
        "agent.use",
        "sandbox.create",
        "sandbox.list",
        "sandbox.delete",
        "session.manage",
        "apikey.manage",
    },
    "developer": {
        "agent.use",
        "sandbox.create",
        "sandbox.list",
        "session.manage",
        "apikey.manage",
    },
    "viewer": {
        "agent.use",
    },
}


def has_permission(role: str, permission: str) -> bool:
    """Check whether a role has a given permission."""
    permissions = ROLE_PERMISSIONS.get(role, set())
    return permission in permissions


def get_user_role(user: dict) -> str:
    """Extract the user's role from the auth context (stored in scopes)."""
    scopes = user.get("scopes", [])
    # The role is passed as the first scope during token creation
    for scope in scopes:
        if scope in ROLE_PERMISSIONS:
            return scope
    return "viewer"  # Default to most restrictive


def require_role(role: str):
    """Dependency that ensures the current user has at least the specified role.

    Usage:
        @router.get("/admin-only")
        async def admin_endpoint(user=Depends(require_role("admin"))):
            ...
    """

    async def check(user: dict = Depends(get_current_user)) -> dict:
        user_role = get_user_role(user)
        user_permissions = ROLE_PERMISSIONS.get(user_role, set())
        required_permissions = ROLE_PERMISSIONS.get(role, set())

        # The user's role must be a superset of (or equal to) the required role's permissions
        if not required_permissions.issubset(user_permissions):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient role: requires '{role}', have '{user_role}'",
            )
        return user

    return check


def require_permission(permission: str):
    """Dependency that ensures the current user has a specific permission.

    Usage:
        @router.post("/sandboxes")
        async def create_sandbox(user=Depends(require_permission("sandbox.create"))):
            ...
    """

    async def check(user: dict = Depends(get_current_user)) -> dict:
        user_role = get_user_role(user)
        if not has_permission(user_role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing permission: '{permission}' (role: '{user_role}')",
            )
        return user

    return check
