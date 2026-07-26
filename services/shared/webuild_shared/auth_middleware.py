from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from webuild_shared.jwt import JWTManager

_bearer_scheme = HTTPBearer()


def get_jwt_manager() -> JWTManager:
    return JWTManager()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    jwt_manager: JWTManager = Depends(get_jwt_manager),
) -> dict:
    try:
        payload = jwt_manager.verify_token(credentials.credentials, expected_type="access")
        return {"user_id": payload.sub, "scopes": payload.scopes}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Invalid or expired token: {e}",
        )


def require_scope(scope: str):
    async def check(user: dict = Depends(get_current_user)):
        if scope not in user.get("scopes", []):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required scope: {scope}",
            )
        return user
    return check
