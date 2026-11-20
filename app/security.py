from functools import lru_cache
import re
from urllib.error import URLError

import jwt
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from jwt import PyJWKClient, PyJWKClientError
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.config import settings

MFA_REQUIRED_ROLES = {
    "admin",
    "facility_admin",
    "medical_director",
    "clinician",
    "nurse",
    "pharmacist",
    "department_head",
}
STAFF_ADMIN_ROLES = {"admin", "facility_admin", "medical_director"}
MODULE_PATHS = {
    "PHARM": "/api/v1/pharmacy",
    "LAB": "/api/v1/laboratory",
    "BILL": "/api/v1/billing",
    "THR": "/api/v1/theatre",
}
SPECIALIST_DEPARTMENTS = {
    "pharmacist": "PHARM",
    "pharmacy": "PHARM",
    "laboratory": "LAB",
    "cashier": "BILL",
    "billing": "BILL",
    "theatre": "THR",
}


def role_can_access_api(method: str, path: str, staff: dict) -> bool:
    role = staff["role"]
    if role in STAFF_ADMIN_ROLES:
        return True

    if path.startswith(("/api/v1/reminders", "/api/v1/notifications", "/api/v1/support")):
        return True

    module_code = (
        staff.get("department_code")
        if role == "department_head"
        else SPECIALIST_DEPARTMENTS.get(role)
    )
    module_path = MODULE_PATHS.get(module_code)
    if module_path and (path == module_path or path.startswith(f"{module_path}/")):
        return True

    if path in {"/api/v1/departments/patients", "/api/v1/departments/queues"}:
        return role in {
            "department_head",
            "pharmacist",
            "pharmacy",
            "laboratory",
            "cashier",
            "billing",
            "theatre",
            "clinician",
        }

    if role == "clinician" and path in {
        "/api/v1/pharmacy/orders",
        "/api/v1/laboratory/orders",
    }:
        return method in {"GET", "POST"}

    if role == "department_head" or role in SPECIALIST_DEPARTMENTS:
        return False

    if path == "/api/v1/health":
        return True
    if path == "/api/v1/facility":
        return role in {"reception", "nurse", "clinician"}
    if path == "/api/v1/dashboard":
        return role in {"reception", "clinician"}

    patient_collection = path == "/api/v1/patients"
    patient_import = path == "/api/v1/patients/import"
    patient_record = (
        not patient_import
        and re.fullmatch(r"/api/v1/patients/[^/]+", path) is not None
    )
    if patient_collection or patient_import or patient_record:
        if method == "GET":
            return role in {"reception", "records", "clinician"} and patient_collection
        if method == "POST":
            return role in {"reception", "records"} and (
                patient_collection or patient_import
            )
        if method in {"PATCH", "DELETE"}:
            return role == "records" and patient_record
        return False

    if path == "/api/v1/appointments":
        return role in {"reception", "clinician"} and method == "GET"
    if re.fullmatch(r"/api/v1/appointments/[^/]+", path):
        return role == "reception" and method == "PATCH"
    if path == "/api/v1/visits/checkin":
        return role == "reception" and method == "POST"
    if path == "/api/v1/queues":
        return role in {"reception", "nurse", "clinician"} and method == "GET"
    if re.fullmatch(r"/api/v1/queues/[^/]+/call", path):
        return role in {"nurse", "clinician"} and method == "POST"
    if path == "/api/v1/queues/call-next":
        return role in {"nurse", "clinician"} and method == "POST"
    if re.fullmatch(r"/api/v1/triage/[^/]+", path):
        return role in {"nurse", "clinician"} and method == "POST"
    if path == "/api/v1/audit":
        return False
    return False


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

        staff_role = claims.get("staffRole", "staff")
        if staff_role in MFA_REQUIRED_ROLES and claims.get("mfa") is not True:
            return JSONResponse(
                status_code=403,
                content={"detail": "Set up an authenticator app before accessing staff data."},
            )

        request.state.staff_user = {
            "id": claims["sub"],
            "name": claims.get("name"),
            "email": claims.get("email"),
            "role": staff_role,
            "department_code": claims.get("departmentCode"),
        }
        if not role_can_access_api(
            request.method,
            request.url.path,
            request.state.staff_user,
        ):
            return JSONResponse(
                status_code=403,
                content={"detail": "This account is not authorized to access this resource."},
            )
        return await call_next(request)


def require_department_module(
    request: Request,
    department_code: str,
    roles: set[str],
    *,
    allow_clinical: bool = False,
) -> dict:
    staff = getattr(request.state, "staff_user", {})
    role = staff.get("role", "staff")
    assigned_department = staff.get("department_code")

    if role in {"admin", "facility_admin", "medical_director"}:
        return staff
    if role == "department_head":
        if assigned_department == department_code:
            return staff
    elif role in roles:
        if assigned_department == department_code:
            return staff
    elif allow_clinical and role == "clinician":
        return staff

    raise HTTPException(
        status_code=403,
        detail="This account is not authorized for the assigned department.",
    )
