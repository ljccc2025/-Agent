import time
from collections.abc import Awaitable, Callable
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from opspilot.config import settings
from opspilot.api import webhook_router, diagnose_router

def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="OpsPilot AI: 自动化故障排查与根因分析 Agent 平台",
        docs_url="/docs",
        redoc_url="/redoc"
    )

    # 跨域配置：生产环境安全加固，禁止携带凭据与全通配符叠加
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 请求计时中间件 (采用高精度单调时钟)
    @application.middleware("http")
    async def add_process_time_header(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        start_time = time.perf_counter()
        response = await call_next(request)
        process_time = time.perf_counter() - start_time
        response.headers["X-Process-Time"] = f"{process_time:.4f}s"
        return response

    @application.get("/healthz", tags=["System"])
    async def healthz() -> dict[str, object]:
        return {
            "status": "healthy",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "read_only_mode": settings.READ_ONLY_MODE
        }

    @application.get("/", tags=["System"])
    async def root() -> dict[str, object]:
        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "message": "OpsPilot AIOps RCA Agent is running",
            "docs": "/docs"
        }

    @application.get("/favicon.ico", include_in_schema=False)
    async def favicon() -> Response:
        return Response(status_code=204)

    # 挂载业务路由
    application.include_router(webhook_router)
    application.include_router(diagnose_router)

    # 挂载静态 UI 控制台
    import os
    from fastapi.staticfiles import StaticFiles
    ui_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "ui")
    if os.path.exists(ui_dir):
        application.mount("/ui", StaticFiles(directory=ui_dir, html=True), name="ui")

    return application

app = create_app()
