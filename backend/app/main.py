"""
FastAPI application entrypoint.

Run with:
    uvicorn app.main:app --reload
"""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import sessions, chat
from app.core import db
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    logging.basicConfig(level=settings.log_level)

    app = FastAPI(
        title="Zylabs AI Research Copilot",
        version="0.1.0",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup():
        db.init_db()

    app.include_router(sessions.router)
    app.include_router(chat.router)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    return app


app = create_app()