import os

from fastapi import APIRouter

from app.api.routes import items, login, private, users, utils
from app.core.config import settings

api_router = APIRouter()
api_router.include_router(login.router)
api_router.include_router(users.router)
api_router.include_router(utils.router)
api_router.include_router(items.router)

if os.environ.get("WEBHOOK_ENABLED") == "1":
    from app.webhooks.routes import router as webhook_router

    api_router.include_router(webhook_router)


if settings.FASTAPI_ENV == "development" and os.environ.get("WEBHOOK_ENABLED") != "1":
    api_router.include_router(private.router)
