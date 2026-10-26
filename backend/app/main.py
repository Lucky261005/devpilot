import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import auth, github, qa, repositories, reviews
from app.core.config import Settings, get_settings
from app.core.db import SessionLocal, get_db
from app.core.logging import configure_logging, request_id_var

log = logging.getLogger("app")
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    worker = None
    if settings.run_worker_in_process:
        from app.workers.queue import Worker

        worker = Worker(SessionLocal, settings)
        worker.start()
    yield
    if worker:
        worker.stop_event.set()


app = FastAPI(title="DevPilot API", version="0.1.0", lifespan=lifespan)


# Interactive docs and the schema are for local development only.
DOCS_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}
# The API returns JSON only: nothing may load, run or frame it.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"


def _security_headers(response: Response, path: str, settings: Settings) -> Response:
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["referrer-policy"] = "no-referrer"
    response.headers["x-frame-options"] = "DENY"
    if path not in DOCS_PATHS:  # Swagger UI needs its own scripts; it only exists in development
        response.headers["content-security-policy"] = API_CSP
    if settings.env != "development" and settings.hsts_seconds:
        response.headers["strict-transport-security"] = f"max-age={settings.hsts_seconds}"
    return response


@app.middleware("http")
async def guard(request: Request, call_next):
    rid = request.headers.get("x-request-id", "")[:64] or uuid.uuid4().hex[:16]
    token = request_id_var.set(rid)
    try:
        settings = get_settings()
        path = request.url.path
        if settings.env != "development" and path in DOCS_PATHS:
            return _security_headers(JSONResponse({"detail": "Not Found"}, status_code=404), path, settings)
        length = request.headers.get("content-length")
        if length and length.isdigit() and int(length) > settings.max_upload_bytes + 1_000_000:
            return _security_headers(
                JSONResponse({"detail": "Request body too large."}, status_code=413), path, settings
            )
        # Without Content-Length the multipart parser would spool an unbounded upload to disk.
        if not length and request.headers.get("content-type", "").startswith("multipart/"):
            return _security_headers(
                JSONResponse({"detail": "Content-Length required for uploads."}, status_code=411), path, settings
            )
        # CSRF: cookies are SameSite=Lax, and state-changing calls must carry a custom header,
        # which a cross-site form cannot set.
        if request.method in UNSAFE and request.headers.get("x-devpilot-csrf") != "1":
            return _security_headers(JSONResponse({"detail": "Missing CSRF header."}, status_code=403), path, settings)
        response = await call_next(request)
        response.headers["x-request-id"] = rid
        return _security_headers(response, path, settings)
    finally:
        request_id_var.reset(token)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        {"detail": exc.detail, "request_id": request_id_var.get()},
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    errors = [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse({"detail": "Invalid request.", "errors": errors}, status_code=422)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": "Internal server error.", "request_id": request_id_var.get()}, status_code=500)


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.get("/api/settings")
def public_settings(settings: Settings = Depends(get_settings)):
    """What the UI needs to explain data flow. Never includes secrets."""
    return {
        "registration": settings.registration_mode,  # never the invite code
        "llm": {
            "provider": settings.llm_provider if settings.llm_configured else None,
            "model": settings.active_llm_model if settings.llm_configured else None,
            "configured": settings.llm_configured,
            "local": settings.llm_is_local,
        },
        "github": {
            "configured": settings.github_configured,
            "scopes": "read-only (GitHub App: contents, metadata, pull requests)",
        },
        "limits": {
            "max_upload_bytes": settings.max_upload_bytes,
            "max_repo_bytes": settings.max_repo_bytes,
            "max_file_bytes": settings.max_file_bytes,
            "reviews_per_hour": settings.reviews_per_hour,
            "reviews_global_per_hour": settings.reviews_global_per_hour,
        },
        "local_import_enabled": bool(settings.allowed_local_roots),
        "retention_days": settings.retention_days,
    }


for r in (auth.router, repositories.router, qa.router, reviews.router, github.router):
    app.include_router(r)
