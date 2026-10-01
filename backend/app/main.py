"""SatQuery AI backend entrypoint.

Existing UI -> FastAPI -> Supabase. No AI/model layer is implemented here --
see CLAUDE.md and README.md for the milestone scope.
"""
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import analysis, conversations, evidence, health, imagery, jobs, profile, reports, results, projects, validation
from app.api.routes import settings as settings_routes  # `settings` below is the app config
from app.core.config import get_settings
from app.core.exceptions import ApiError
from app.core.logging import configure_logging
from app.db.supabase import supabase_config_problem
from app.schemas.common import ApiResponse

settings = get_settings()
configure_logging(settings.APP_ENV)
logger = logging.getLogger(__name__)

# Said once at startup, in the terminal running the backend (e.g. `npm run dev`):
# on a fresh clone this is the usual reason history won't load.
_supabase_problem = supabase_config_problem(settings)
if _supabase_problem:
    logger.warning("[satquery] %s", _supabase_problem)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description=(
        "REST API foundation connecting the existing SatQuery AI frontend to Supabase. "
        "AI models and agentic orchestration are intentionally not implemented in this milestone."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    # Lets the browser read the report's filename (POST /reports).
    expose_headers=["Content-Disposition"],
)


@app.exception_handler(ApiError)
def handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ApiResponse.fail(exc.code, exc.message, details=exc.details).model_dump(),
    )


@app.exception_handler(RequestValidationError)
def handle_validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content=ApiResponse.fail("VALIDATION_ERROR", "Request payload failed validation.").model_dump(),
    )


@app.exception_handler(Exception)
def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # Never leak stack traces or internals to the frontend.
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=ApiResponse.fail("INTERNAL_ERROR", "An unexpected error occurred.").model_dump(),
    )


API_PREFIX = "/api/v1"
app.include_router(health.router, prefix=API_PREFIX)
app.include_router(conversations.router, prefix=API_PREFIX)
app.include_router(imagery.router, prefix=API_PREFIX)
app.include_router(analysis.router, prefix=API_PREFIX)
app.include_router(jobs.router, prefix=API_PREFIX)
app.include_router(results.router, prefix=API_PREFIX)
app.include_router(evidence.router, prefix=API_PREFIX)
app.include_router(profile.router, prefix=API_PREFIX)
app.include_router(settings_routes.router, prefix=API_PREFIX)
app.include_router(projects.router, prefix=API_PREFIX)
app.include_router(reports.router, prefix=API_PREFIX)
app.include_router(validation.router, prefix=API_PREFIX)
# Also expose /api/validation directly for dev/debug endpoints
app.include_router(validation.router, prefix="/api")
