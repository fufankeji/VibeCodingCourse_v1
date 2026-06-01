from fastapi import APIRouter

from app.api import contracts, sessions, items, fields, events, reports, review_config

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(contracts.router, prefix="/contracts", tags=["contracts"])
api_router.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
api_router.include_router(items.router, prefix="/sessions", tags=["items"])
api_router.include_router(fields.router, prefix="/sessions", tags=["fields"])
api_router.include_router(events.router, prefix="/sessions", tags=["events"])
api_router.include_router(reports.router, prefix="/sessions", tags=["reports"])
api_router.include_router(review_config.router, prefix="/review-config", tags=["review-config"])
