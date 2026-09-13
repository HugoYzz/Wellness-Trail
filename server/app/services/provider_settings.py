"""单用户 Provider 偏好：只持久化选择和模型名，不持久化 API Key。"""
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import User
from app.providers.base import AIProvider
from app.providers.registry import create_provider, default_provider_id, provider_specs

LOCAL_USERNAME = "local"


def get_or_create_local_user(db: Session) -> User:
    user = db.scalars(select(User).order_by(User.id)).first()
    if user is None:
        user = User(username=LOCAL_USERNAME, settings_json={})
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def get_provider_preferences(db: Session) -> tuple[str, dict[str, str]]:
    user = get_or_create_local_user(db)
    settings = user.settings_json or {}
    available = provider_specs()
    provider_id = str(settings.get("ai_provider") or default_provider_id())
    if provider_id not in available:
        provider_id = default_provider_id()
    raw_models = settings.get("ai_models") or {}
    models = {
        str(key): str(value).strip()
        for key, value in raw_models.items()
        if key in available and str(value).strip()
    }
    return provider_id, models


def set_provider_preference(db: Session, provider_id: str, model: str | None) -> None:
    available = provider_specs()
    if provider_id not in available:
        raise ValueError(f"未知 Provider：{provider_id}")
    user = get_or_create_local_user(db)
    settings = dict(user.settings_json or {})
    models = dict(settings.get("ai_models") or {})
    if model is not None and model.strip():
        models[provider_id] = model.strip()
    settings["ai_provider"] = provider_id
    settings["ai_models"] = models
    user.settings_json = settings
    db.add(user)
    db.commit()


def get_active_provider(db: Session) -> AIProvider:
    provider_id, models = get_provider_preferences(db)
    return create_provider(provider_id, models.get(provider_id))
