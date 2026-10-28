from fastapi import APIRouter, HTTPException, Response, status

from app.db.db_schemas import EmailSettingsResponse, EmailSettingsUpdate
from app.dependencies import CurrentUser, SessionDep
from app.services import email_service
from app.services.email_service import EmailNotificationError

router = APIRouter(
    prefix="/notification-settings",
    tags=["notification settings"],
)


def _response(user: CurrentUser) -> EmailSettingsResponse:
    return EmailSettingsResponse(
        notification_email=user.notification_email,
        delivery_configured=email_service.email_configured(),
    )


@router.get("/email", response_model=EmailSettingsResponse)
async def get_email_settings(user: CurrentUser) -> EmailSettingsResponse:
    return _response(user)


@router.put("/email", response_model=EmailSettingsResponse)
async def update_email_settings(
    data: EmailSettingsUpdate,
    session: SessionDep,
    user: CurrentUser,
) -> EmailSettingsResponse:
    user.notification_email = data.notification_email
    await session.flush()
    return _response(user)


@router.post("/email/test", status_code=status.HTTP_204_NO_CONTENT)
async def send_test_email(user: CurrentUser) -> Response:
    if user.notification_email is None:
        raise HTTPException(status_code=409, detail="Save an email address first")
    if not email_service.email_configured():
        raise HTTPException(status_code=503, detail="Email delivery is not configured on the server")
    try:
        await email_service.send_test_email(user.notification_email)
    except EmailNotificationError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return Response(status_code=status.HTTP_204_NO_CONTENT)
