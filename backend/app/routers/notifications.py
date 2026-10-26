from fastapi import APIRouter, Depends

from app.deps import current_user
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("")
def list_(user: dict = Depends(current_user)):
    return notification_service.list_notifications(user["id"])


@router.post("/{notification_id}/read")
def read(notification_id: int, user: dict = Depends(current_user)):
    return notification_service.mark_read(user["id"], notification_id)      # naturally idempotent
