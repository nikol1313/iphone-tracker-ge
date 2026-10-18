from fastapi import APIRouter, HTTPException

from app.db.db_schemas import RefreshResponse
from app.dependencies import CurrentAdmin, SessionDep
from app.scraper.scrape_alta import AltaCrawlError
from app.scraper.scrape_zoommer import ZoommerCrawlError
from app.services.errors import NotFoundError, RefreshInProgressError
from app.services.product_service import (
    list_product_listings,
    require_active_product,
)
from app.services.scraper_service import refresh_full_catalog

router = APIRouter(tags=["refresh"])


@router.post(
    "/products/{product_id}/refresh",
    response_model=RefreshResponse,
)
async def refresh_product(
    product_id: int,
    session: SessionDep,
    _: CurrentAdmin,
) -> RefreshResponse:
    try:
        await require_active_product(session, product_id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


    await session.commit()

    try:
        summary = await refresh_full_catalog()
    except RefreshInProgressError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except (AltaCrawlError, ZoommerCrawlError) as error:
        raise HTTPException(
            status_code=502,
            detail="The external store could not be refreshed",
        ) from error

    listings = await list_product_listings(
        session,
        product_id=product_id,
        include_inactive=False,
        limit=100,
        offset=0,
    )
    return RefreshResponse(
        crawl_run_id=summary.crawl_run_id or 0,
        crawl_run_ids=list(
            summary.crawl_run_ids
            or ((summary.crawl_run_id,) if summary.crawl_run_id else ())
        ),
        requested_product_id=product_id,
        products_found=summary.scraped,
        listings_created=summary.listings_created,
        listings_updated=summary.listings_updated,
        prices_recorded=summary.prices_recorded,
        listings=listings.items,
    )
