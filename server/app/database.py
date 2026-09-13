"""数据库引擎与会话工厂（SQLite + WAL，架构 §4/§5）。"""
import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker

# data/ 在项目根（server/ 的上一级），.gitignore 已排除
DATA_DIR = Path(__file__).resolve().parents[2] / "data"
DB_PATH = Path(
    os.environ.get("KANGJI_DB_PATH") or DATA_DIR / "kangji.sqlite3"
).resolve()


class Base(DeclarativeBase):
    """全部 ORM 模型的基类。"""


def make_engine(db_path: Path | str | None = None):
    path = Path(db_path) if db_path else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragma(dbapi_conn, _record):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA busy_timeout=5000")
        cur.close()

    return engine


engine = make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    """FastAPI 依赖：请求级会话。"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
