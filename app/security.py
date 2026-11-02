from functools import lru_cache
from urllib.error import URLError

import jwt
from fastapi import Request
from fastapi.responses import JSONResponse
from jwt import PyJWKClient, PyJWKClientError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config import settings


@lru_cache(maxsize=1)
def get_jwks_client() -> PyJWKClient:
    return PyJWKClient(settings.auth_jwks_url, cache_keys=True)


def verify_access_token(token: str) -> dict:
    signing_key = get_jwks_client().get_signing_key_from_jwt(token)
    return jwt.decode(
        token,
        signing_key.key,
        algorithms=["EdDSA"],
        issuer=settings.auth_issuer,
        audience=settings.auth_issuer,
        options={"require": ["exp", "iss", "aud", "sub"]},
    )


class StaffAuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if (
            not request.url.path.startswith("/api/v1/")
            or request.url.path == "/api/v1/health"
            or request.method == "OPTIONS"
        ):
            return await call_next(request)

        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Sign in is required to access this resource."},
                headers={"WWW-Authenticate": "Bearer"},
            )

        try:
            claims = verify_access_token(token)
        except jwt.InvalidTokenError:
            return JSONResponse(
                status_code=401,
                content={"detail": "Your session is invalid or has expired. Please sign in again."},
                headers={"WWW-Authenticate": "Bearer"},
            )
        except (PyJWKClientError, URLError, OSError):
            return JSONResponse(
                status_code=503,
                content={"detail": "Authentication verification is temporarily unavailable."},
            )

        if claims.get("facilityId") != settings.facility_code:
            return JSONResponse(
                status_code=403,
                content={"detail": "This account cannot access this facility."},
            )

        request.state.staff_user = {
            "id": claims["sub"],
            "role": claims.get("staffRole", "staff"),
        }
        return await call_next(request)
