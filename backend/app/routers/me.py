from fastapi import APIRouter, Depends

from app.deps import current_user
from app.services import user_service

router = APIRouter(tags=["me"])


@router.get("/me")
def me(user: dict = Depends(current_user)):
    return user_service.me(user)
