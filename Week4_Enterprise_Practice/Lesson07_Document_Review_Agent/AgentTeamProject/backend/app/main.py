import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import settings
from app.database import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Save main event loop reference so background threads can schedule coroutines
    from app.core import main_loop
    main_loop.loop = asyncio.get_event_loop()
    # Initialize database tables
    init_db()
    # Ensure storage directory exists
    os.makedirs(settings.storage_path, exist_ok=True)
    from app.database import SessionLocal
    from app.services.document_parse_worker import worker_loop

    stop_event = asyncio.Event()
    worker_task = asyncio.create_task(worker_loop(SessionLocal, stop_event=stop_event))
    try:
        yield
    finally:
        stop_event.set()
        worker_task.cancel()
        try:
            await worker_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="水土保持方案智能评审 API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
def health():
    return {"status": "ok", "version": "1.0.0"}
