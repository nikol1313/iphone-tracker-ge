from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.db.db_schemas import Page, PriceExtremesResponse, PriceHistoryResponse
from app.dependencies import SessionDep
from app.services.errors import NotFoundError
from app.services.product_service import (
    get_product_price_extremes,
    list_product_prices,
)

router = APIRouter(tags=["price history"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.get(
    "/products/{product_id}/prices",
    response_model=Page[PriceHistoryResponse],
)
async def product_prices(
    product_id: int,
    session: SessionDep,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[PriceHistoryResponse]:
    try:
        return await list_product_prices(
            session,
            product_id=product_id,
            limit=limit,
            offset=offset,
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get(
    "/products/{product_id}/prices/extremes",
    response_model=PriceExtremesResponse,
)
async def product_price_extremes(
    product_id: int,
    session: SessionDep,
    currency: str = "GEL",
) -> PriceExtremesResponse:
    normalized_currency = currency.strip()
    if (
        len(normalized_currency) != 3
        or not normalized_currency.isascii()
        or not normalized_currency.isalpha()
    ):
        raise HTTPException(
            status_code=422,
            detail="currency must be a three-letter code",
        )
    try:
        return await get_product_price_extremes(
            session,
            product_id=product_id,
            currency=currency,
        )
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
