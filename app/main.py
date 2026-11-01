"""应用入口：路由装配、工具注册自检与前端托管。

路由分两组：用户侧接口只认登录态，知识/审核相关接口额外要求客服角色；
SPA 回退放在最后注册，避免把 /api 下的 404 也吞成 index.html。
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.actions import router as actions_router
from app.api.agent import router as agent_router
from app.api.auth import router as auth_router
from app.api.chat import router as chat_router
from app.api.commerce import router as commerce_router
from app.api.conversations import router as conversations_router
from app.api.feedback import router as feedback_router
from app.api.kb import router as kb_router
from app.api.review import router as review_router
from app.api.system import router as system_router
from app.core.auth import staff_user
from app.graph import runtime

logger = logging.getLogger(__name__)
FRONTEND = Path(__file__).resolve().parents[1] / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    from app.tools import registry
    Path("data").mkdir(exist_ok=True)
    registry.scan_builtin()
    # 工具注册是硬性契约：少一个就拒绝启动，避免线上跑到一半才发现工具缺失。
    expected = {"query_order", "list_orders", "query_product", "query_faq",
                "submit_refund", "create_ticket"}
    if {tool.name for tool in registry.builtin_specs()} != expected:
        raise RuntimeError("业务工具注册不完整")
    await runtime.init_graph()
    try:
        yield
    finally:
        await runtime.close_graph()


app = FastAPI(title="Eshop Assistant", version="0.2.0", lifespan=lifespan)
for router in [auth_router, actions_router, chat_router, agent_router, commerce_router,
               conversations_router, feedback_router, system_router]:
    app.include_router(router)
# 知识库与审核接口只对客服开放，统一在装配处加依赖，避免每个 endpoint 各写一遍。
for router in [kb_router, review_router]:
    app.include_router(router, dependencies=[Depends(staff_user)])

app.mount("/assets", StaticFiles(directory=FRONTEND / "assets", check_dir=False), name="assets")


@app.get("/health", include_in_schema=False)
async def health():
    return {"service": "eshop-assistant", "status": "running"}


@app.get("/{path:path}", include_in_schema=False)
async def frontend(path: str):
    if path == "api" or path.startswith("api/"):
        raise HTTPException(404, "接口不存在")
    if not (FRONTEND / "index.html").is_file():
        raise HTTPException(503, "前端尚未构建，请在 frontend 目录运行 npm run build")
    return FileResponse(FRONTEND / "index.html")
