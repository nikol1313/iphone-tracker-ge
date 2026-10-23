import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


from app.api import (
    alerts,
    auth,
    listings,
    notification_settings,
    prices,
    products,
    refresh,
    search,
    tracked_products,
)
from app.conf import settings
from app.db.sess import engine
from app.services.scraper_service import run_refresh_schedule


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    settings.jwt_secret()
    scheduler = (
        asyncio.create_task(run_refresh_schedule())
        if settings.REFRESH_SCHEDULER_ENABLED
        else None
    )
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.cancel()
            with suppress(asyncio.CancelledError):
                await scheduler
        await engine.dispose()


app = FastAPI(
    title="iPhone Price Monitor API",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(search.router)
app.include_router(products.router)
app.include_router(listings.router)
app.include_router(prices.router)
app.include_router(tracked_products.router)
app.include_router(alerts.router)
app.include_router(notification_settings.router)
app.include_router(refresh.router)

app.mount("/static", StaticFiles(directory="app/static", html=True), name="static")


@app.get("/")
async def serve_index(request: Request) -> FileResponse:
    return FileResponse("app/static/index.html")

