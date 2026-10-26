from fastapi import APIRouter

from app.schemas import LoginIn, RegisterIn
from app.services import user_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
def register(body: RegisterIn):
    return user_service.register_student(body)


@router.post("/login")
def login(body: LoginIn):
    return user_service.login(body.email, body.password)
