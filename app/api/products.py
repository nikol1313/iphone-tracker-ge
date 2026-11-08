from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.db.db_schemas import (
    Page,
    ProductCreate,
    ProductSpecsResponse,
    ProductSummary,
    ProductUpdate,
)
from app.dependencies import CurrentAdmin, SessionDep
from app.services import product_service, spec_service
from app.services.errors import ConflictError, NotFoundError

router = APIRouter(prefix="/products", tags=["products"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post("", response_model=ProductSummary, status_code=status.HTTP_201_CREATED)
async def create_product(
    data: ProductCreate,
    session: SessionDep,
    _: CurrentAdmin,
) -> ProductSummary:
    try:
        return await product_service.create_product(session, data)
    except ConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("", response_model=Page[ProductSummary])
async def list_products(
    session: SessionDep,
    brand: str | None = None,
    model: str | None = None,
    storage: str | None = None,
    color: str | None = None,
    include_inactive: bool = False,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[ProductSummary]:
    return await product_service.list_products(
        session,
        brand=brand,
        model=model,
        storage=storage,
        color=color,
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
    )


@router.get("/{product_id}", response_model=ProductSummary)
async def get_product(
    product_id: int,
    session: SessionDep,
) -> ProductSummary:
    try:
        return await product_service.get_product_summary(session, product_id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.get("/{product_id}/specs", response_model=ProductSpecsResponse)
async def get_product_specs(
    product_id: int,
    session: SessionDep,
) -> ProductSpecsResponse:
    try:
        return await spec_service.get_product_specs(session, product_id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.patch("/{product_id}", response_model=ProductSummary)
async def update_product(
    product_id: int,
    data: ProductUpdate,
    session: SessionDep,
    _: CurrentAdmin,
) -> ProductSummary:
    try:
        return await product_service.update_product(session, product_id, data)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.delete("/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    session: SessionDep,
    _: CurrentAdmin,
) -> Response:
    try:
        await product_service.soft_delete_product(session, product_id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
