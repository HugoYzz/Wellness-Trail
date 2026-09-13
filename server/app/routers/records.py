"""records CRUD API（架构 §5/§2.3）。

- GET    /api/records          按日期区间/类型/日期查询
- POST   /api/records          新建（Pydantic 闸 + 体重相对 ±5kg 警告）
- PUT    /api/records/{id}     修改
- DELETE /api/records/{id}     删除
- GET    /api/records/meta     前端表单元数据（枚举与槽位）
"""
from datetime import date as Date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import schemas
from app.database import get_db
from app.models import Record

router = APIRouter(prefix="/api/records", tags=["records"])

# 相对合理性闸（§2.3）：超 ±5kg 不硬拒，返回 warning 供确认卡标红复核
WEIGHT_RELATIVE_GATE_KG = 5.0


def _to_out(r: Record) -> dict:
    """ORM → 对外 JSON（键名统一：fields_json 序列化为 fields）。"""
    return {
        "id": r.id,
        "type": r.type,
        "date": r.date.isoformat(),
        "slot": r.slot,
        "fields": r.fields_json,
        "raw_text": r.raw_text,
        "source": r.source,
        "confirmed": r.confirmed,
        "created_at": r.created_at.isoformat() if r.created_at else None,
    }


@router.get("")
def list_records(
    start: Date | None = None,
    end: Date | None = None,
    date: Date | None = None,
    type: schemas.RecordType | None = None,
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(Record).order_by(Record.date.desc(), Record.id.desc())
    if date is not None:
        stmt = stmt.where(Record.date == date)
    else:
        if start is not None:
            stmt = stmt.where(Record.date >= start)
        if end is not None:
            stmt = stmt.where(Record.date <= end)
    if type is not None:
        stmt = stmt.where(Record.type == type)
    return [_to_out(r) for r in db.scalars(stmt).all()]


@router.post("")
def create_record(
    payload: schemas.RecordCreate, db: Session = Depends(get_db)
) -> dict:
    warnings: list[str] = []
    if payload.type == "weight":
        warnings.extend(_weight_relative_check(db, payload))

    rec = Record(
        type=payload.type,
        date=payload.date,
        slot=payload.slot,
        fields_json=payload.fields,
        raw_text=payload.raw_text,
        source=payload.source,
        confirmed=payload.confirmed,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    out = _to_out(rec)
    out["warnings"] = warnings
    return out


@router.put("/{record_id}")
def update_record(
    record_id: int,
    payload: schemas.RecordUpdate,
    db: Session = Depends(get_db),
) -> dict:
    rec = db.get(Record, record_id)
    if rec is None:
        raise HTTPException(404, f"record {record_id} 不存在")

    fields_set = payload.model_fields_set
    candidate = schemas.RecordCreate(
        type=payload.type if "type" in fields_set else rec.type,
        date=payload.date if "date" in fields_set else rec.date,
        slot=payload.slot if "slot" in fields_set else rec.slot,
        fields=payload.fields if "fields" in fields_set else rec.fields_json,
        raw_text=payload.raw_text if "raw_text" in fields_set else rec.raw_text,
        source=rec.source,
        confirmed=rec.confirmed,
    )
    warnings: list[str] = []
    if candidate.type == "weight":
        warnings = _weight_relative_check(db, candidate, exclude_record_id=rec.id)
    rec.type = candidate.type
    rec.date = candidate.date
    rec.slot = candidate.slot
    rec.fields_json = candidate.fields
    rec.raw_text = candidate.raw_text
    db.commit()
    db.refresh(rec)
    out = _to_out(rec)
    out["warnings"] = warnings
    return out


@router.delete("/{record_id}")
def delete_record(record_id: int, db: Session = Depends(get_db)) -> dict:
    rec = db.get(Record, record_id)
    if rec is None:
        raise HTTPException(404, f"record {record_id} 不存在")
    db.delete(rec)
    db.commit()
    return {"deleted": record_id}


@router.get("/meta")
def records_meta() -> dict:
    """前端表单元数据：11 类的槽位与枚举（对齐 §2.3）。"""
    return {
        "types": {
            t: {
                "slots": list(slots),
                "enums": _type_enums(t),
            }
            for t, slots in schemas.TYPE_SLOTS.items()
        }
    }


@router.get("/{record_id}")
def get_record(record_id: int, db: Session = Depends(get_db)) -> dict:
    rec = db.get(Record, record_id)
    if rec is None:
        raise HTTPException(404, f"record {record_id} 不存在")
    return _to_out(rec)


def _type_enums(t: str) -> dict:
    return {
        "sweet_drink": {"level": schemas.SWEET_DRINK_LEVELS},
        "night_hunger": {"level": schemas.NIGHT_HUNGER_LEVELS},
        "exercise": {"kind": schemas.EXERCISE_KINDS},
        "supplement": {
            "item": schemas.SUPPLEMENT_ITEMS,
            "timing": schemas.SUPPLEMENT_TIMINGS,
        },
        "body": {"site": schemas.BODY_SITES},
    }.get(t, {})


def _weight_relative_check(
    db: Session,
    payload: schemas.RecordCreate,
    exclude_record_id: int | None = None,
) -> list[str]:
    """体重相对闸：与上一条同 slot 的已确认体重比较，超 ±5kg 给 warning（不拒收）。"""
    stmt = select(Record).where(
            Record.type == "weight",
            Record.slot == payload.slot,
            Record.confirmed.is_(True),
            Record.date <= payload.date,
            Record.id.isnot(None),
        )
    if exclude_record_id is not None:
        stmt = stmt.where(Record.id != exclude_record_id)
    prev = db.scalars(
        stmt.order_by(Record.date.desc(), Record.id.desc()).limit(1)
    ).first()
    if prev is None or prev.id is None:
        return []
    prev_kg = float(prev.fields_json.get("kg", 0))
    new_kg = float(payload.fields.get("kg", 0))
    diff = new_kg - prev_kg
    if abs(diff) > WEIGHT_RELATIVE_GATE_KG:
        return [
            f"体重较上次（{prev.date} {prev_kg}kg）变化 {diff:+.1f}kg，"
            f"超过 ±{WEIGHT_RELATIVE_GATE_KG:g}kg 相对闸，请复核数值/单位"
        ]
    return []
