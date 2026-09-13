"""设置与数据管理 API（架构 §7.5：数据导出一键 JSON 全量备份；§10-P3 Provider/费用）。

- GET /api/settings/usage   Provider 信息 + token 用量与费用估算
- GET /api/settings/export  全量 JSON 备份（记录/会话/洞察反馈/知识库元数据/基线）
"""
import json
import math
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import ChatRun, Message
from app.providers.registry import create_provider, provider_specs
from app.services import vector_kb
from app.services.backup_restore import (
    BackupValidationError,
    build_backup,
    drill_restore,
    restore_backup,
)
from app.services.provider_settings import (
    get_provider_preferences,
    set_provider_preference,
)
from app.services.provider_evaluation import (
    evaluate_provider,
    get_evaluations,
    save_evaluation,
)

router = APIRouter(prefix="/api/settings", tags=["settings"])

# DeepSeek 官方牌价（元/百万 token，deepseek-chat）；估算口径，改牌价改这里
PRICE = {
    "input_miss": 2.0,
    "input_hit": 0.2,
    "output": 8.0,
}


class ProviderSelectionIn(BaseModel):
    provider_id: str = Field(min_length=1, max_length=32)
    model: str | None = Field(default=None, max_length=128)
    allow_cloud_health_data: bool = False


class ProviderEvaluationIn(BaseModel):
    model: str | None = Field(default=None, max_length=128)


class RestoreIn(BaseModel):
    backup: dict
    confirmation: str = Field(min_length=1, max_length=32)


def _provider_out(
    spec,
    model: str,
    *,
    selected: bool,
    evaluation: dict | None = None,
) -> dict:
    return {
        "id": spec.id,
        "name": spec.name,
        "model": model,
        "base_url": spec.base_url,
        "is_local": spec.is_local,
        "configured": spec.configured,
        "selected": selected,
        "credential_status": (
            "本地无需" if spec.is_local else "已配置" if spec.configured else "未配置"
        ),
        "capabilities": {
            "stream": spec.supports_stream,
            "tools": spec.supports_tools,
            "json": spec.supports_json,
        },
        "evaluation": evaluation if evaluation and evaluation.get("model") == model else None,
    }


@router.get("/providers")
def get_providers(db: Session = Depends(get_db)) -> dict:
    selected_id, models = get_provider_preferences(db)
    specs = provider_specs()
    evaluations = get_evaluations(db)
    providers = [
        _provider_out(
            spec,
            models.get(spec.id, spec.model),
            selected=spec.id == selected_id,
            evaluation=evaluations.get(spec.id),
        )
        for spec in specs.values()
    ]
    evaluated = [provider for provider in providers if provider["evaluation"]]
    recommended = None
    if evaluated:
        recommended = max(
            evaluated,
            key=lambda provider: (
                provider["evaluation"]["score"],
                provider["is_local"],
                -provider["evaluation"]["avg_latency_ms"],
            ),
        )
    return {
        "selected_provider_id": selected_id,
        "recommended_provider_id": recommended["id"] if recommended else None,
        "selection_note": (
            f"当前评测推荐 {recommended['name']}：先比较合成集得分，同分时优先本地与较低延迟。"
            if recommended
            else "尚无评测数据；请至少运行一个 Provider 的三项合成评测。"
        ),
        "providers": providers,
        "privacy_note": "本地模型不离开设备；云端模型仅在你主动选择后接收本轮问题、必要历史与检索片段。",
    }


@router.put("/provider")
def select_provider(
    payload: ProviderSelectionIn,
    db: Session = Depends(get_db),
) -> dict:
    specs = provider_specs()
    spec = specs.get(payload.provider_id)
    if spec is None:
        raise HTTPException(404, "Provider 不存在")
    if not spec.configured:
        raise HTTPException(409, f"请先在 server/.env 配置 {spec.api_key_env}")
    if not spec.is_local and not payload.allow_cloud_health_data:
        raise HTTPException(422, "切换云端模型前需要确认健康上下文将发送给该服务商")
    set_provider_preference(db, spec.id, payload.model)
    return get_providers(db)


@router.post("/providers/{provider_id}/test")
async def test_provider(provider_id: str, db: Session = Depends(get_db)) -> dict:
    specs = provider_specs()
    spec = specs.get(provider_id)
    if spec is None:
        raise HTTPException(404, "Provider 不存在")
    if not spec.configured:
        return {"ok": False, "message": f"未配置 {spec.api_key_env}"}
    _, models = get_provider_preferences(db)
    provider = create_provider(provider_id, models.get(provider_id))
    return await provider.check_connection()


@router.post("/providers/{provider_id}/evaluate")
async def run_provider_evaluation(
    provider_id: str,
    payload: ProviderEvaluationIn,
    db: Session = Depends(get_db),
) -> dict:
    specs = provider_specs()
    spec = specs.get(provider_id)
    if spec is None:
        raise HTTPException(404, "Provider 不存在")
    if not spec.configured:
        raise HTTPException(409, f"请先在 server/.env 配置 {spec.api_key_env}")
    _, models = get_provider_preferences(db)
    model = payload.model.strip() if payload.model and payload.model.strip() else models.get(provider_id)
    provider = create_provider(provider_id, model)
    try:
        result = await evaluate_provider(provider)
    except Exception as exc:
        raise HTTPException(502, f"评测失败：{exc}") from exc
    save_evaluation(db, result)
    return result


@router.get("/rag")
def get_rag_status() -> dict:
    state = vector_kb.status()
    return {
        **state,
        "keyword_retrieval": "SQLite FTS5 / BM25",
        "fusion": "RRF" if state["enabled"] else "未启用",
        "reranker": "首版关闭（预留）",
    }


@router.post("/rag/reindex")
def rebuild_rag_index(db: Session = Depends(get_db)) -> dict:
    try:
        return vector_kb.rebuild(db)
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/usage")
def get_usage(db: Session = Depends(get_db)) -> dict:
    legacy_messages = int(
        db.scalar(select(func.count(Message.id)).where(Message.role == "assistant")) or 0
    )
    completed_runs = db.scalars(
        select(ChatRun).where(ChatRun.status == "completed").order_by(ChatRun.id)
    ).all()
    prompt_t = sum(int((run.usage_json or {}).get("prompt_tokens") or 0) for run in completed_runs)
    completion_t = sum(int((run.usage_json or {}).get("completion_tokens") or 0) for run in completed_runs)
    cache_hit_t = sum(int((run.usage_json or {}).get("prompt_cache_hit_tokens") or 0) for run in completed_runs)
    total_t = sum(int((run.usage_json or {}).get("total_tokens") or 0) for run in completed_runs)
    measured_messages = sum(run.usage_source == "provider" for run in completed_runs)
    estimated_messages = sum(run.usage_source == "estimated" for run in completed_runs)
    known_assistant_ids = {run.assistant_message_id for run in completed_runs if run.assistant_message_id}
    guidance_prefix = "早，昨晚睡得怎么样？"
    legacy_model_messages = db.scalars(
        select(Message).where(
            Message.role == "assistant",
            ~Message.content.startswith(guidance_prefix),
        )
    ).all()
    legacy_unknown = [item for item in legacy_model_messages if item.id not in known_assistant_ids]
    all_messages = db.scalars(select(Message).order_by(Message.chat_id, Message.id)).all()
    preceding_user: dict[int, Message] = {}
    user_before_assistant: dict[int, Message] = {}
    for item in all_messages:
        if item.role == "user":
            preceding_user[item.chat_id] = item
        elif item.role == "assistant" and item.chat_id in preceding_user:
            user_before_assistant[item.id] = preceding_user[item.chat_id]

    def estimate(text_value: str) -> int:
        ascii_chars = sum(ord(char) < 128 for char in text_value)
        return max(1, math.ceil(ascii_chars / 4) + len(text_value) - ascii_chars)

    legacy_estimated_messages = sum(bool(item.content.strip()) for item in legacy_unknown)
    unknown_messages = len(legacy_unknown) - legacy_estimated_messages
    legacy_prompt_estimate = sum(
        int(item.prompt_tokens or estimate(user_before_assistant[item.id].content) + 4)
        for item in legacy_unknown
        if item.content.strip() and item.id in user_before_assistant
    )
    legacy_completion_estimate = sum(
        int(item.completion_tokens or estimate(item.content))
        for item in legacy_unknown
        if item.content.strip()
    )
    prompt_t += legacy_prompt_estimate
    completion_t += legacy_completion_estimate

    deepseek_runs = [run for run in completed_runs if run.provider_id == "deepseek"]
    deepseek_prompt = sum(int((run.usage_json or {}).get("prompt_tokens") or 0) for run in deepseek_runs)
    deepseek_completion = sum(int((run.usage_json or {}).get("completion_tokens") or 0) for run in deepseek_runs)
    deepseek_cache = sum(int((run.usage_json or {}).get("prompt_cache_hit_tokens") or 0) for run in deepseek_runs)
    # DeepSeek prompt_tokens 为总输入（含命中），只按逐次运行的 Provider 归属计费。
    cache_miss_t = max(deepseek_prompt - deepseek_cache, 0)
    cost = (
        cache_miss_t / 1e6 * PRICE["input_miss"]
        + deepseek_cache / 1e6 * PRICE["input_hit"]
        + deepseek_completion / 1e6 * PRICE["output"]
    )
    selected_id, models = get_provider_preferences(db)
    spec = provider_specs()[selected_id]
    model = models.get(selected_id, spec.model)
    return {
        "provider": _provider_out(spec, model, selected=True),
        "assistant_messages": len(completed_runs) + len(legacy_unknown),
        "usage_coverage": {
            "measured_messages": measured_messages,
            "estimated_messages": estimated_messages + legacy_estimated_messages,
            "historical_estimated_messages": legacy_estimated_messages,
            "unknown_messages": unknown_messages,
            "legacy_assistant_rows": legacy_messages,
        },
        "tokens": {
            "prompt_total": prompt_t,
            "prompt_cache_hit": cache_hit_t,
            "prompt_cache_miss": cache_miss_t,
            "completion": completion_t,
            "total_legacy": total_t + legacy_prompt_estimate + legacy_completion_estimate,
        },
        "cost_yuan": round(cost, 4),
        "price_note": (
            f"DeepSeek 历史运行估算：输入未命中 {PRICE['input_miss']} 元/M、"
            f"命中 {PRICE['input_hit']} 元/M、输出 {PRICE['output']} 元/M；历史补算不计费"
            if deepseek_runs
            else "本地模型不产生 API 费用；旧回复按文本长度估算 Token，不计入任何云端费用。"
        ),
    }


@router.get("/export")
def export_backup(db: Session = Depends(get_db)) -> Response:
    """导出带格式版本、关系信息和恢复所需台账的完整 JSON。"""
    backup = build_backup(db)
    filename = f"kangji-backup-{date.today().isoformat()}.json"
    return Response(
        content=json.dumps(backup, ensure_ascii=False, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/restore/validate")
def validate_restore(backup: dict) -> dict:
    try:
        return drill_restore(backup)
    except (BackupValidationError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("/restore")
def restore_from_backup(payload: RestoreIn, db: Session = Depends(get_db)) -> dict:
    if payload.confirmation != "RESTORE":
        raise HTTPException(422, "确认文本必须为 RESTORE")
    try:
        return restore_backup(db, payload.backup)
    except (BackupValidationError, TypeError, ValueError) as exc:
        raise HTTPException(422, str(exc)) from exc
