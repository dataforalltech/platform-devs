"""Application API composition."""

from fastapi import APIRouter

from app.api.internal import router as internal_router
from app.api.v1 import v1_router

api_router = APIRouter(prefix="/api")
api_router.include_router(v1_router)
api_router.include_router(internal_router)
__all__ = ["api_router"]
