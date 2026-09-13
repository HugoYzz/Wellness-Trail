"""可选的本地向量知识库。

使用 Ollama 生成 embedding，Qdrant Client 本地磁盘模式保存向量。任何向量层故障
都由调用方回退到 FTS5；这里只处理增强召回，不替代业务数据库。
"""
from __future__ import annotations

import logging
from collections.abc import Iterable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.models import KbChunk

logger = logging.getLogger(__name__)
EMBED_TIMEOUT = httpx.Timeout(connect=5, read=120, write=120, pool=5)
BATCH_SIZE = 8


def _qdrant_modules():
    try:
        from qdrant_client import QdrantClient, models
    except ImportError as exc:
        raise RuntimeError(
            "未安装 qdrant-client；请在 server 目录重新安装项目依赖"
        ) from exc
    return QdrantClient, models


def _client():
    QdrantClient, _ = _qdrant_modules()
    return QdrantClient(path=config.RAG_VECTOR_PATH)


def _embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    with httpx.Client(timeout=EMBED_TIMEOUT) as client:
        response = client.post(
            f"{config.RAG_EMBED_BASE_URL.rstrip('/')}/api/embed",
            json={"model": config.RAG_EMBED_MODEL, "input": texts},
        )
    if response.status_code != 200:
        raise RuntimeError(
            f"Embedding 服务 HTTP {response.status_code}: {response.text[:180]}"
        )
    embeddings = response.json().get("embeddings") or []
    if len(embeddings) != len(texts):
        raise RuntimeError("Embedding 服务返回数量与输入不一致")
    return embeddings


def _batches(items: list, size: int = BATCH_SIZE) -> Iterable[list]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def status() -> dict:
    base = {
        "enabled": config.RAG_VECTOR_ENABLED,
        "collection": config.RAG_VECTOR_COLLECTION,
        "path": config.RAG_VECTOR_PATH,
        "embedding_model": config.RAG_EMBED_MODEL,
        "ready": False,
        "points": 0,
        "message": "向量检索未启用，当前使用 FTS5",
    }
    if not config.RAG_VECTOR_ENABLED:
        return base
    client = None
    try:
        client = _client()
        if not client.collection_exists(config.RAG_VECTOR_COLLECTION):
            base["message"] = "尚未建立向量索引"
            return base
        info = client.get_collection(config.RAG_VECTOR_COLLECTION)
        base.update(
            ready=True,
            points=int(info.points_count or 0),
            message="Qdrant 本地索引可用",
        )
    except Exception as exc:  # noqa: BLE001 - 状态接口需要可读诊断
        base["message"] = str(exc)
    finally:
        if client is not None:
            client.close()
    return base


def rebuild(db: Session) -> dict:
    if not config.RAG_VECTOR_ENABLED:
        raise RuntimeError("请先设置 RAG_VECTOR_ENABLED=1 并重启后端")
    chunks = list(db.scalars(select(KbChunk).order_by(KbChunk.id)).all())
    if not chunks:
        raise RuntimeError("知识库中没有可索引的分块")

    QdrantClient, models = _qdrant_modules()
    client = QdrantClient(path=config.RAG_VECTOR_PATH)
    try:
        first_vector = _embed([chunks[0].content])[0]
        if client.collection_exists(config.RAG_VECTOR_COLLECTION):
            client.delete_collection(config.RAG_VECTOR_COLLECTION)
        client.create_collection(
            collection_name=config.RAG_VECTOR_COLLECTION,
            vectors_config=models.VectorParams(
                size=len(first_vector), distance=models.Distance.COSINE
            ),
        )

        indexed = 0
        for batch_no, chunk_batch in enumerate(_batches(chunks)):
            if batch_no == 0:
                vectors = [first_vector]
                if len(chunk_batch) > 1:
                    vectors.extend(_embed([chunk.content for chunk in chunk_batch[1:]]))
            else:
                vectors = _embed([chunk.content for chunk in chunk_batch])
            points = [
                models.PointStruct(
                    id=chunk.id,
                    vector=vector,
                    payload={
                        "chunk_id": chunk.id,
                        "content": chunk.content,
                        "title": chunk.title,
                        "heading": chunk.heading,
                        "section_no": chunk.section_no,
                        "source_plan": chunk.source_plan,
                    },
                )
                for chunk, vector in zip(chunk_batch, vectors, strict=True)
            ]
            client.upsert(
                collection_name=config.RAG_VECTOR_COLLECTION,
                points=points,
                wait=True,
            )
            indexed += len(points)
    finally:
        client.close()
    return {"ok": True, "indexed": indexed, **status()}


def search(query: str, source_plan: str | None = None, top: int = 20) -> list[dict]:
    if not config.RAG_VECTOR_ENABLED or not query.strip():
        return []
    client = None
    try:
        client = _client()
        if not client.collection_exists(config.RAG_VECTOR_COLLECTION):
            return []
        _, models = _qdrant_modules()
        query_filter = None
        if source_plan:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="source_plan", match=models.MatchValue(value=source_plan)
                    )
                ]
            )
        result = client.query_points(
            collection_name=config.RAG_VECTOR_COLLECTION,
            query=_embed([query])[0],
            query_filter=query_filter,
            limit=top,
            with_payload=True,
        )
        return [
            {
                **(point.payload or {}),
                "chunk_id": int((point.payload or {}).get("chunk_id", point.id)),
                "vector_score": float(point.score),
                "retrieval": "vector",
            }
            for point in result.points
        ]
    except Exception as exc:  # noqa: BLE001 - 可选增强，失败时安全回退 FTS5
        logger.warning("Vector KB unavailable, falling back to FTS5: %s", exc)
        return []
    finally:
        if client is not None:
            client.close()
