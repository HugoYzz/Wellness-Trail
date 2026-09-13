"""今日计划 API：生成、确认与当天调整。"""
from datetime import date as Date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.todo_plan import build_today_plan, update_today_plan

router = APIRouter(prefix="/api/todos", tags=["todos"])


class TodayPlanUpdate(BaseModel):
    action: Literal["confirm", "skip", "restore", "rest", "reset"]
    task_key: str | None = None


@router.get("/today")
def get_today_plan(date: Date | None = None, db: Session = Depends(get_db)) -> dict:
    return build_today_plan(db, date)


@router.patch("/today")
def patch_today_plan(
    payload: TodayPlanUpdate,
    date: Date | None = None,
    db: Session = Depends(get_db),
) -> dict:
    try:
        return update_today_plan(
            db,
            date or Date.today(),
            action=payload.action,
            task_key=payload.task_key,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
