"""知识库检索服务（架构 §6.4 RAG-lite）。

- SQLite FTS5（trigram 分词，适配中文）+ bm25 取 top-5
- source_plan 分域过滤（两代方案不混用）
- FTS 表为 kb_chunks 的倒排副本：ensure_fts() 幂等重建（行数不一致时）
- 查询 <3 字符（trigram 不可用）时退化为 LIKE
"""
from sqlalchemy import func, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models import KbChunk

TOP_K = 5


def _fts_phrase(query: str) -> str:
    """Treat arbitrary user text as a literal FTS5 phrase."""
    return f'"{query.replace("\"", "\"\"")}"'


def ensure_fts(db: Session) -> None:
    """幂等建立/刷新 FTS5 索引（trigram）。"""
    db.execute(text("CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5("
                    "content, title, heading, source_plan, section_no, "
                    "tokenize='trigram')"))
    db.commit()
    fts_count = db.execute(text("SELECT count(*) FROM kb_fts")).scalar() or 0
    chunk_count = db.scalar(select(func.count()).select_from(KbChunk)) or 0
    if fts_count != chunk_count:
        db.execute(text("DELETE FROM kb_fts"))
        db.execute(text(
            "INSERT INTO kb_fts(rowid, content, title, heading, source_plan, section_no) "
            "SELECT id, content, title, heading, source_plan, section_no FROM kb_chunks"
        ))
        db.commit()


def _keyword_search(
    db: Session,
    query: str,
    source_plan: str | None = None,
    top: int = TOP_K,
) -> list[dict]:
    """bm25 全文检索，返回带溯源的候选块。"""
    query = (query or "").strip()
    if not query:
        return []

    where_plan = ""
    params: dict = {"top": top}
    if source_plan:
        where_plan = " AND source_plan = :plan"
        params["plan"] = source_plan

    def like_search() -> list:
        sql = text(
            "SELECT id AS rowid, content, title, heading, section_no, source_plan, "
            "0 AS score FROM kb_chunks "
            "WHERE content LIKE :like" + where_plan + " LIMIT :top"
        )
        like_params = {**params, "like": f"%{query}%"}
        return db.execute(sql, like_params).mappings().all()

    if len(query) >= 3:  # trigram 可用
        sql = text(
            "SELECT rowid, content, title, heading, section_no, source_plan, "
            "bm25(kb_fts) AS score FROM kb_fts "
            "WHERE kb_fts MATCH :q" + where_plan + " "
            "ORDER BY score LIMIT :top"
        )
        try:
            rows = db.execute(sql, {**params, "q": _fts_phrase(query)}).mappings().all()
        except OperationalError:
            rows = like_search()
    else:  # 短查询退化 LIKE
        rows = like_search()

    return [
        {
            "chunk_id": r["rowid"],
            "content": r["content"],
            "title": r["title"],
            "heading": r["heading"],
            "section_no": r["section_no"],
            "source_plan": r["source_plan"],
        }
        for r in rows
    ]


def _rrf_merge(rankings: list[list[dict]], top: int) -> list[dict]:
    """Reciprocal Rank Fusion：合并关键词与向量名次，不混用原始分数尺度。"""
    scores: dict[int, float] = {}
    items: dict[int, dict] = {}
    sources: dict[int, set[str]] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            chunk_id = int(item["chunk_id"])
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (60 + rank)
            items.setdefault(chunk_id, item)
            sources.setdefault(chunk_id, set()).add(item.get("retrieval", "fts5"))
    ordered = sorted(scores, key=scores.get, reverse=True)[:top]
    return [
        {
            **items[chunk_id],
            "retrieval": "+".join(sorted(sources[chunk_id])),
            "fusion_score": scores[chunk_id],
        }
        for chunk_id in ordered
    ]


def search(
    db: Session,
    query: str,
    source_plan: str | None = None,
    top: int = TOP_K,
) -> list[dict]:
    """混合检索：FTS5 始终可用，向量层按配置增强并可安全回退。"""
    candidate_top = max(top * 4, 20)
    keyword_hits = _keyword_search(db, query, source_plan, candidate_top)
    for item in keyword_hits:
        item["retrieval"] = "fts5"

    from app.services import vector_kb

    vector_hits = vector_kb.search(query, source_plan, candidate_top)
    if not vector_hits:
        return keyword_hits[:top]
    return _rrf_merge([keyword_hits, vector_hits], top)


def format_context(chunks: list[dict]) -> str:
    """检索命中 → 注入系统提示的知识库上下文块（带溯源标注）。"""
    if not chunks:
        return "（本轮无知识库命中）"
    parts = []
    for c in chunks:
        anchor = c["section_no"] or c["heading"]
        src = "8月主线方案" if c["source_plan"] == "august_fatloss" else "7月健康知识库"
        parts.append(
            f"【{src} · {c['title']}{' §' + anchor if anchor else ''}】\n{c['content']}"
        )
    return "\n\n".join(parts)
