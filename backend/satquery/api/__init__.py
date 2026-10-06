"""HTTP API (FastAPI). Versioned under ``/api/v1``."""

from fastapi import APIRouter

from satquery.api.routes import query, system

API_V1_PREFIX = "/api/v1"

api_router = APIRouter()
api_router.include_router(query.router)
api_router.include_router(system.router)

__all__ = ["API_V1_PREFIX", "api_router"]
