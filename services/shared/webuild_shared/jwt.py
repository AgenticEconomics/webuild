import os
import time
import uuid
from dataclasses import dataclass, field

import jwt


@dataclass
class TokenPayload:
    sub: str
    scopes: list[str] = field(default_factory=list)
    iss: str = "webuild.datoms.cn"
    aud: list[str] = field(default_factory=lambda: ["webuild"])
    exp: int = 0
    iat: int = 0
    jti: str = ""


class JWTManager:
    def __init__(
        self,
        secret: str | None = None,
        algorithm: str | None = None,
        access_expire_minutes: int | None = None,
        refresh_expire_days: int | None = None,
    ):
        self.secret = secret or os.environ["JWT_SECRET"]
        self.algorithm = algorithm or os.environ.get("JWT_ALGORITHM", "HS256")
        self.access_expire = int(
            os.environ.get("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", access_expire_minutes or 60)
        ) * 60
        self.refresh_expire = int(
            os.environ.get("JWT_REFRESH_TOKEN_EXPIRE_DAYS", refresh_expire_days or 7)
        ) * 86400

    def create_access_token(self, user_id: str, scopes: list[str] | None = None) -> str:
        now = int(time.time())
        payload = {
            "sub": user_id,
            "scopes": scopes or ["agent.use"],
            "iss": "webuild.datoms.cn",
            "aud": ["webuild"],
            "iat": now,
            "exp": now + self.access_expire,
            "jti": str(uuid.uuid4()),
            "type": "access",
        }
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)

    def create_refresh_token(self, user_id: str) -> str:
        now = int(time.time())
        payload = {
            "sub": user_id,
            "iss": "webuild.datoms.cn",
            "aud": ["webuild"],
            "iat": now,
            "exp": now + self.refresh_expire,
            "jti": str(uuid.uuid4()),
            "type": "refresh",
        }
        return jwt.encode(payload, self.secret, algorithm=self.algorithm)

    def verify_token(self, token: str, expected_type: str = "access") -> TokenPayload:
        decoded = jwt.decode(
            token,
            self.secret,
            algorithms=[self.algorithm],
            audience=["webuild"],
            issuer="webuild.datoms.cn",
        )
        if decoded.get("type") != expected_type:
            raise jwt.InvalidTokenError(f"Expected {expected_type} token")
        return TokenPayload(
            sub=decoded["sub"],
            scopes=decoded.get("scopes", []),
            iss=decoded.get("iss", ""),
            aud=decoded.get("aud", []),
            exp=decoded["exp"],
            iat=decoded["iat"],
            jti=decoded.get("jti", ""),
        )
