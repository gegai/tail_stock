from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.config import settings

# 后端应用实例。所有业务接口都挂在统一前缀下。
app = FastAPI(title=settings.app_name, version="0.1.0")

# 允许本机前端开发服务、预览服务和桌面壳页面访问后端接口。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 统一注册业务路由。
app.include_router(router, prefix="/api")


@app.get("/health")
async def health():
    """健康检查接口，用于确认后端服务已启动。"""
    return {"status": "ok", "app": settings.app_name}
