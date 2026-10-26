from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.deps import current_user
from app.services import coordinator_service

router = APIRouter(tags=["calendar"])


@router.get("/calendar")
def calendar(from_: Optional[str] = Query(None, alias="from"), to: Optional[str] = None, user: dict = Depends(current_user)):
    return coordinator_service.calendar_events(user, from_, to)
