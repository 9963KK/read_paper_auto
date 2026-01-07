"""
FastAPI 主应用
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from loguru import logger

from src.api.routes import router
from src.config import settings
from src.services.feishu_bot import feishu_bot
from src.services.craft_client import craft_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动
    logger.info("Starting application...")
    logger.info(f"Server: {settings.server_host}:{settings.server_port}")
    logger.info(f"LLM: {settings.llm_base_url} / {settings.llm_model_name}")

    yield

    # 关闭
    logger.info("Shutting down application...")
    await feishu_bot.close()
    await craft_client.close()


# 创建 FastAPI 应用
app = FastAPI(
    title="论文自动归档系统",
    description="基于 LangGraph 的半自动论文管理工作流",
    version="0.1.0",
    lifespan=lifespan
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(router, prefix="/api")


@app.get("/")
async def root():
    """根路由"""
    return {
        "name": "论文自动归档系统",
        "version": "0.1.0",
        "status": "running"
    }


@app.get("/health")
async def health():
    """健康检查"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.server_host,
        port=settings.server_port,
        reload=True,
        log_level=settings.log_level.lower()
    )
