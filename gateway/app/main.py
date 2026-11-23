import uuid
from typing import Callable

import httpx
import jwt
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.security import validate_access_token

app = FastAPI(title="Corporate Parking API Gateway")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Headers stripped before forwarding downstream (hop-by-hop + internal service auth)
STRIPPED_REQUEST_HEADERS = {
    "host",
    "content-length",
    "connection",
    "keep-alive",
    "transfer-encoding",
    "x-internal-service-token",
}

STRIPPED_RESPONSE_HEADERS = {
    "content-length",
    "transfer-encoding",
    "connection",
    "keep-alive",
}


def _error_response(status_code: int, code: str, message: str, request_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "request_id": request_id}},
        headers={"X-Request-ID": request_id},
    )


def _resolve_route(path: str) -> tuple[str | None, bool]:
    """Return (downstream_base_url, requires_jwt). Returns (None, False) if unmapped."""
    if path.startswith("/api/v1/auth"):
        return settings.USER_AUTH_SERVICE_URL, False
    if path.startswith("/api/v1/users"):
        return settings.USER_AUTH_SERVICE_URL, True
    if path.startswith("/api/v1/vehicles"):
        return settings.VEHICLE_SERVICE_URL, True
    if path.startswith("/api/v1/parking"):
        return settings.PARKING_SERVICE_URL, True
    if path.startswith("/api/v1/payments"):
        return settings.PAYMENT_SERVICE_URL, True
    return None, False


def _default_http_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10.0, follow_redirects=False)


# Swappable factory for unit/integration tests
app.state.http_client_factory = _default_http_client_factory


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return _error_response(500, "INTERNAL_ERROR", "An unexpected error occurred.", request_id)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok", "service": settings.SERVICE_NAME}


@app.api_route("/internal/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def block_internal_routes(full_path: str, request: Request):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    return _error_response(404, "NOT_FOUND", "Endpoint not found.", request_id)


@app.api_route("/api/v1/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_api_v1(full_path: str, request: Request):
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    path = f"/api/v1/{full_path}"
    downstream_base, requires_jwt = _resolve_route(path)

    if downstream_base is None:
        return _error_response(404, "NOT_FOUND", "Endpoint not found.", request_id)

    # Early RS256 JWT validation for protected routes (downstream services also validate independently)
    if requires_jwt:
        auth_header = request.headers.get("authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return _error_response(401, "UNAUTHENTICATED", "Missing or invalid authorization header.", request_id)
        token = auth_header.removeprefix("Bearer ").strip()
        try:
            validate_access_token(token)
        except (jwt.PyJWTError, ValueError, OSError):
            return _error_response(401, "UNAUTHENTICATED", "Invalid or expired access token.", request_id)

    # Strip hop-by-hop headers and ANY externally supplied X-Internal-Service-Token
    forward_headers = {
        k: v for k, v in request.headers.items() if k.lower() not in STRIPPED_REQUEST_HEADERS
    }
    forward_headers["X-Request-ID"] = request_id

    target_url = f"{downstream_base.rstrip('/')}{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    body = await request.body()
    client_factory: Callable[[], httpx.AsyncClient] = app.state.http_client_factory

    try:
        async with client_factory() as client:
            upstream = await client.request(
                method=request.method,
                url=target_url,
                headers=forward_headers,
                content=body,
            )
    except httpx.HTTPError:
        return _error_response(
            503,
            "SERVICE_UNAVAILABLE",
            "Downstream service is currently unavailable.",
            request_id,
        )

    out_response = Response(
        content=upstream.content,
        status_code=upstream.status_code,
    )
    for k, v in upstream.headers.multi_items():
        if k.lower() not in STRIPPED_RESPONSE_HEADERS:
            out_response.headers.append(k, v)
    out_response.headers["X-Request-ID"] = request_id
    return out_response
