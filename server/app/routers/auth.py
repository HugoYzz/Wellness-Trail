"""首次 PIN 设置、会话登录与锁定 API。"""
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import access_control

router = APIRouter(prefix="/api/auth", tags=["auth"])


class PinIn(BaseModel):
    pin: str = Field(pattern=r"^\d{6,12}$")


def _client_id(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _set_session(response: Response) -> int:
    token, ttl = access_control.create_session()
    response.set_cookie(
        key=access_control.COOKIE_NAME,
        value=token,
        max_age=ttl,
        httponly=True,
        samesite="strict",
        secure=False,
        path="/",
    )
    return ttl


@router.get("/status")
def auth_status(request: Request, db: Session = Depends(get_db)) -> dict:
    token = request.cookies.get(access_control.COOKIE_NAME)
    return {
        "pin_configured": access_control.pin_is_configured(db),
        "authenticated": access_control.session_is_valid(token),
        "expires_at": access_control.session_expires_at(token),
    }


@router.post("/setup")
def setup_pin(
    payload: PinIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    if access_control.pin_is_configured(db):
        raise HTTPException(409, "访问 PIN 已设置")
    try:
        access_control.configure_pin(db, payload.pin)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    access_control.clear_failed_logins(_client_id(request))
    ttl = _set_session(response)
    return {"ok": True, "authenticated": True, "session_seconds": ttl}


@router.post("/login")
def login(
    payload: PinIn,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    if not access_control.pin_is_configured(db):
        raise HTTPException(428, "请先在本机创建访问 PIN")
    client_id = _client_id(request)
    retry_after = access_control.login_retry_after(client_id)
    if retry_after:
        raise HTTPException(
            429,
            f"尝试次数过多，请在 {retry_after} 秒后重试",
            headers={"Retry-After": str(retry_after)},
        )
    if not access_control.authenticate_pin(db, payload.pin):
        access_control.record_failed_login(client_id)
        raise HTTPException(401, "PIN 不正确")
    access_control.clear_failed_logins(client_id)
    ttl = _set_session(response)
    return {"ok": True, "authenticated": True, "session_seconds": ttl}


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    access_control.revoke_session(request.cookies.get(access_control.COOKIE_NAME))
    response.delete_cookie(access_control.COOKIE_NAME, path="/")
    return {"ok": True}
