from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Response, status

from app.db.db_schemas import AlertCreate, AlertResponse, Page
from app.dependencies import CurrentUser, SessionDep
from app.services.alert_service import (
    create_alert,
    delete_alert,
    get_alert_response,
    list_alerts,
    update_alert,
)
from app.services.errors import ConflictError, NotFoundError

router = APIRouter(tags=["alerts"])
Limit = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0)]


@router.post(
    "/products/{product_id}/alerts",
    response_model=AlertResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_alert(
    product_id: int,
    data: AlertCreate,
    session: SessionDep,
    user: CurrentUser,
) -> AlertResponse:
    try:
        alert = await create_alert(
            session,
            user_id=user.id,
            product_id=product_id,
            data=data,
        )
        return await get_alert_response(session, alert)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@router.get("/alerts", response_model=Page[AlertResponse])
async def get_alerts(
    session: SessionDep,
    user: CurrentUser,
    limit: Limit = 50,
    offset: Offset = 0,
) -> Page[AlertResponse]:
    return await list_alerts(
        session,
        user_id=user.id,
        limit=limit,
        offset=offset,
    )


@router.put("/alerts/{alert_id}", response_model=AlertResponse)
async def replace_alert(
    alert_id: int,
    data: AlertCreate,
    session: SessionDep,
    user: CurrentUser,
) -> AlertResponse:
    try:
        alert = await update_alert(
            session,
            user_id=user.id,
            alert_id=alert_id,
            data=data,
        )
        return await get_alert_response(session, alert)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.delete("/alerts/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_alert(
    alert_id: int,
    session: SessionDep,
    user: CurrentUser,
) -> Response:
    try:
        await delete_alert(session, user_id=user.id, alert_id=alert_id)
    except NotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
