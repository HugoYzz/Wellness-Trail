"""康迹后端入口（架构 §3/§10-P0）。

启动（server/ 目录下）：
    uvicorn app.main:app --reload --port 8001
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.database import SessionLocal, engine
from app.models import Base
from app.routers import auth, chat, records, settings, stats, todos
from app.services import access_control

app = FastAPI(title="康迹 API", version="0.1.0")

# 开发期前端（Vite 默认 5173）与局域网同源访问
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

PUBLIC_API_PATHS = {
    "/api/health",
    "/api/auth/status",
    "/api/auth/setup",
    "/api/auth/login",
    "/api/auth/logout",
}


@app.middleware("http")
async def require_access_session(request: Request, call_next):
    """除健康检查与登录流程外，统一保护全部业务 API。"""
    path = request.url.path.rstrip("/") or "/"
    if (
        request.method == "OPTIONS"
        or not path.startswith("/api/")
        or path in PUBLIC_API_PATHS
    ):
        return await call_next(request)

    token = request.cookies.get(access_control.COOKIE_NAME)
    if access_control.session_is_valid(token):
        return await call_next(request)

    with SessionLocal() as db:
        configured = access_control.pin_is_configured(db)
    if not configured:
        return JSONResponse(
            status_code=428,
            content={"detail": "请先创建访问 PIN"},
            headers={"Cache-Control": "no-store"},
        )
    return JSONResponse(
        status_code=401,
        content={"detail": "会话已失效，请重新输入 PIN"},
        headers={"Cache-Control": "no-store"},
    )

app.include_router(auth.router)
app.include_router(records.router)
app.include_router(chat.router)
app.include_router(stats.router)
app.include_router(settings.router)
app.include_router(todos.router)


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "app": "康迹"}


# 兜底建表：正式迁移走 Alembic（server/alembic），此处保证脚本直跑不缺表
Base.metadata.create_all(bind=engine)
