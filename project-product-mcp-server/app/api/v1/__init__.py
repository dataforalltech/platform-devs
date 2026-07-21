"""Authenticated `/api/v1` router with package router discovery."""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

from fastapi import APIRouter, Depends

from app.core.security import bind_authenticated_claims

logger = logging.getLogger(__name__)
v1_router = APIRouter(prefix="/v1", dependencies=[Depends(bind_authenticated_claims)])
_modules_path = str(Path(__file__).parents[2] / "modules")
for _finder, _name, _is_package in pkgutil.iter_modules([_modules_path]):
    if not _is_package:
        continue
    module = importlib.import_module(f"app.modules.{_name}.routers")
    router = getattr(module, "router", None)
    if router is not None:
        v1_router.include_router(router)
        logger.info("module_registered name=%s", _name)
