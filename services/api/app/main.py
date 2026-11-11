import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.database import engine
from app.core.schema import ensure_schema
from app.routers import applications, assistant, auth, autoapply, insights, jobs, profile, resumes
from app.services.applications import TransitionError
from app.services.documents import TruthfulnessError
from app.services.documents_io import DocumentError

log = logging.getLogger(__name__)


def _scheduler(stop: threading.Event, interval_minutes: int) -> None:
    from app.core.database import SessionLocal
    from app.services.job_sync import run_due_schedules

    while not stop.wait(max(60, interval_minutes * 60)):
        db = SessionLocal()
        try:
            run_due_schedules(db)
            db.commit()
        except Exception:  # noqa: BLE001 - a failed run is retried on the next tick
            log.exception("Scheduled job search failed")
            db.rollback()
        finally:
            db.close()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_schema(engine)
    # Browser tabs do not survive a restart; close out applications that were in progress.
    from app.core.database import SessionLocal
    from app.services.autoapply.records import recover

    with SessionLocal() as db:
        if recover(db):
            db.commit()
    settings = get_settings()
    stop = threading.Event()
    if settings.scheduler_enabled:
        threading.Thread(target=_scheduler, args=(stop, settings.scheduler_interval_minutes), name="search-scheduler", daemon=True).start()
    yield
    stop.set()


_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="ApplyPilot API", version="0.1.0", lifespan=lifespan)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        if not request.url.path.startswith(_DOCS_PATHS):
            # API responses are data, never pages: nothing may run or load from them.
            headers.setdefault("Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'")
            # Profiles, resumes, and applications must not be kept in shared or disk caches.
            headers.setdefault("Cache-Control", "no-store")
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    # Outermost: refuse requests addressed to any other host name (DNS rebinding).
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_host_list)
    app.include_router(auth.router)
    app.include_router(profile.router)
    app.include_router(resumes.router)
    app.include_router(jobs.router)
    app.include_router(applications.router)
    app.include_router(insights.router)
    app.include_router(assistant.router)
    app.include_router(autoapply.router)

    @app.get("/api/v1/health")
    def health():
        return {
            "status": "ok",
            "demo_mode": settings.demo_mode,
            "integrations": {
                "ai": settings.ai_configured,
                "ai_provider": settings.ai_provider_name,
                "ai_model": settings.anthropic_model if settings.ai_provider_name == "anthropic" else (settings.openai_model if settings.ai_provider_name == "openai" else None),
                "adzuna": settings.adzuna_configured,
                "public_job_sources": settings.public_job_sources,
                "email": settings.email_configured,
                "environment": settings.environment,
                "submission_methods": ["simulated", "manual"],
                "live_submission": [],
            },
        }

    @app.exception_handler(TransitionError)
    async def _transition(_request, exc: TransitionError):
        return JSONResponse(status_code=409, content={"detail": {"code": "invalid_transition", "message": str(exc)}})

    @app.exception_handler(TruthfulnessError)
    async def _truth(_request, exc: TruthfulnessError):
        return JSONResponse(status_code=422, content={"detail": {"code": "untruthful_resume", "message": " ".join(exc.problems)}})

    @app.exception_handler(DocumentError)
    async def _document(_request, exc: DocumentError):
        return JSONResponse(status_code=400, content={"detail": {"code": "invalid_file", "message": str(exc)}})

    return app


app = create_app()
