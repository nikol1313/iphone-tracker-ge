import math
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException

from app.db.db_schemas import RefreshResponse, RefreshStatusResponse
from app.dependencies import CurrentUser, SessionDep
from app.services.errors import RefreshCooldownError, RefreshInProgressError
from app.services.scraper_service import (
    last_refresh_started_at,
    next_manual_refresh_at,
    request_manual_refresh,
)

router = APIRouter(prefix="/refresh", tags=["refresh"])


async def _status(session: SessionDep) -> RefreshStatusResponse:
    return RefreshStatusResponse(
        last_refreshed_at=await last_refresh_started_at(session),
        next_manual_refresh_at=await next_manual_refresh_at(session),
    )


@router.get("", response_model=RefreshStatusResponse)
async def refresh_status(session: SessionDep) -> RefreshStatusResponse:
    return await _status(session)


@router.post("", response_model=RefreshResponse)
async def refresh_catalog(
    session: SessionDep,
    user: CurrentUser,
) -> RefreshResponse:
    try:
        summary = await request_manual_refresh(
            session,
            bypass_cooldown=user.is_admin,
        )
    except RefreshCooldownError as error:
        retry_after = math.ceil(
            (error.available_at - datetime.now(UTC)).total_seconds()
        )
        raise HTTPException(
            status_code=429,
            detail=str(error),
            headers={"Retry-After": str(max(retry_after, 1))},
        ) from error
    except RefreshInProgressError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error

    if not summary.succeeded_stores:
        raise HTTPException(
            status_code=502,
            detail="No store could be refreshed",
        )

    await session.rollback()
    status = await _status(session)
    return RefreshResponse(
        **status.model_dump(),
        crawl_run_ids=list(summary.crawl_run_ids),
        products_found=summary.scraped,
        listings_created=summary.listings_created,
        listings_updated=summary.listings_updated,
        prices_recorded=summary.prices_recorded,
        succeeded_stores=list(summary.succeeded_stores),
        failed_stores=list(summary.failed_stores),
    )
