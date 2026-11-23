import uuid
from fastapi import FastAPI, Request
from app.api.v1.payments import router as payments_router
from app.core.config import settings
from app.core.errors import register_exception_handlers

app = FastAPI(title="Corporate Parking — Payment Service")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


register_exception_handlers(app)
app.include_router(payments_router)


@app.get("/health", tags=["health"])
def health_check():
    return {"status": "ok", "service": settings.SERVICE_NAME}
