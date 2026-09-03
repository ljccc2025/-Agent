import time
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from opspilot.config import settings

def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="OpsPilot AI: 自动化故障排查与根因分析 Agent 平台",
        docs_url="/docs",
        redoc_url="/redoc"
    )

    # 跨域配置
    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 请求计时中间件
    @application.middleware("http")
    async def add_process_time_header(request: Request, call_next):
        start_time = time.time()
        response = await call_next(request)
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = f"{process_time:.4f}s"
        return response

    @application.get("/healthz", tags=["System"])
    def healthz():
        return {
            "status": "healthy",
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "read_only_mode": settings.READ_ONLY_MODE
        }

    @application.get("/", tags=["System"])
    def root():
        return {
            "service": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "message": "OpsPilot AIOps RCA Agent is running",
            "docs": "/docs"
        }

    return application

app = create_app()
