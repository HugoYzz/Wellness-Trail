"""记录域 Pydantic 校验（架构 §2.3 数据字典 + 约束闸）。

这是"三重闸"中的第二闸（后端校验）：数值范围 + 枚举合法 + 槽位规则。
相对上次 ±5kg 双闸在 routers/records.py 中查库实现（不硬拒，返回 warning）。
"""
import re
from datetime import date as Date
from datetime import datetime as DateTime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RecordType = Literal[
    "weight",
    "sleep",
    "meal",
    "sweet_drink",
    "night_hunger",
    "exercise",
    "step",
    "waist",
    "supplement",
    "body",
    "note",
]

# ---- 槽位规则（§2.3）----
WEIGHT_SLOTS = ("am", "evening")
MEAL_SLOTS = ("breakfast", "lunch", "dinner", "snack")

# ---- 枚举（§2.3，对齐真实 xlsx 下拉与方案原文）----
SWEET_DRINK_LEVELS = ("0杯", "无糖", "三分糖", "半糖", "全糖")
NIGHT_HUNGER_LEVELS = ("没饿", "加餐预案", "破戒")
EXERCISE_KINDS = ("swim", "strength")
SUPPLEMENT_ITEMS = ("vitd3", "zinc", "copper")
SUPPLEMENT_TIMINGS = ("早餐后", "晚餐后")
BODY_SITES = ("腰", "踝", "肠胃")

_BEDTIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


# ---- 各 type 的 fields_json schema ----
class WeightFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kg: float = Field(ge=40, le=200)  # 绝对闸；相对 ±5kg 见 router
    note: str | None = None


class SleepFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bedtime: str  # "HH:MM"，如 "00:30"（跨零点，归属规则见 §2.3）

    @model_validator(mode="after")
    def _check_bedtime(self):
        if not _BEDTIME_RE.match(self.bedtime):
            raise ValueError("bedtime 须为 HH:MM（24 小时制），如 23:40 / 00:30")
        return self


class MealFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    desc: str = Field(min_length=1, max_length=500)


class SweetDrinkFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["0杯", "无糖", "三分糖", "半糖", "全糖"]
    desc: str | None = None


class NightHungerFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    level: Literal["没饿", "加餐预案", "破戒"]


class ExerciseFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["swim", "strength"]
    duration_min: int | None = Field(default=None, ge=0, le=300)
    done: bool | None = None

    @model_validator(mode="after")
    def _check_kind_fields(self):
        if self.kind == "swim" and self.duration_min is None:
            raise ValueError("游泳记录须提供 duration_min（分钟）")
        if self.kind == "strength" and self.done is None:
            raise ValueError("力量训练记录须提供 done（完成/未做）")
        return self


class StepFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: int = Field(ge=0, le=50000)


class WaistFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cm: float = Field(ge=50, le=200)


class SupplementFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item: Literal["vitd3", "zinc", "copper"]
    dose: str = Field(min_length=1, max_length=64)  # 如 "2000IU" / "15-25mg"
    timing: Literal["早餐后", "晚餐后"]
    taken: bool


class BodyFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    site: Literal["腰", "踝", "肠胃"]
    level: int | None = Field(default=None, ge=1, le=10)  # 疼痛/不适评分
    symptom: str | None = None


class NoteFields(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)


FIELDS_MODEL: dict[str, type[BaseModel]] = {
    "weight": WeightFields,
    "sleep": SleepFields,
    "meal": MealFields,
    "sweet_drink": SweetDrinkFields,
    "night_hunger": NightHungerFields,
    "exercise": ExerciseFields,
    "step": StepFields,
    "waist": WaistFields,
    "supplement": SupplementFields,
    "body": BodyFields,
    "note": NoteFields,
}

# 各 type 的合法 slot 集合；空元组表示该 type 无 slot（须为 None）
TYPE_SLOTS: dict[str, tuple[str, ...]] = {
    "weight": WEIGHT_SLOTS,
    "meal": MEAL_SLOTS,
    "sleep": (),
    "sweet_drink": (),
    "night_hunger": (),
    "exercise": (),
    "step": (),
    "waist": (),
    "supplement": (),
    "body": (),
    "note": (),
}


class RecordCreate(BaseModel):
    """手动/聊天/导入共用的入参模型。"""

    model_config = ConfigDict(extra="forbid")

    type: RecordType
    date: Date
    slot: str | None = None
    fields: dict
    raw_text: str = ""
    source: Literal["chat", "manual", "import"] = "manual"
    confirmed: bool = True

    @model_validator(mode="after")
    def _validate_fields_and_slot(self):
        allowed = TYPE_SLOTS[self.type]
        if allowed:
            if self.slot not in allowed:
                raise ValueError(
                    f"type={self.type} 的 slot 必须是 {allowed} 之一，收到 {self.slot!r}"
                )
        elif self.slot is not None:
            raise ValueError(f"type={self.type} 不应有 slot，收到 {self.slot!r}")
        # 校验并规范化 fields_json（非法枚举/超范围在此抛出）
        model = FIELDS_MODEL[self.type](**self.fields)
        self.fields = model.model_dump(exclude_none=True)
        return self


class RecordUpdate(BaseModel):
    """修改记录（架构 §5：个人应用做轻，直接更新字段）。"""

    model_config = ConfigDict(extra="forbid")

    type: RecordType | None = None
    date: Date | None = None
    slot: str | None = None
    fields: dict | None = None
    raw_text: str | None = None

    @model_validator(mode="after")
    def _at_least_one(self):
        if not self.model_fields_set:
            raise ValueError("至少提供 type / date / slot / fields / raw_text 之一")
        return self


class RecordOut(BaseModel):
    # ORM 属性名为 fields_json，对外统一用 "fields"（alias 双向生效）
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: int
    type: RecordType
    date: Date
    slot: str | None
    fields: dict = Field(alias="fields_json")
    raw_text: str
    source: str
    confirmed: bool
    created_at: DateTime | None = None
