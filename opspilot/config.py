from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_NAME: str = "OpsPilot AI"
    APP_VERSION: str = "0.1.0"

    # API 服务端配置
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8080
    API_WORKERS: int = 1

    # 大模型与推理配置
    LLM_API_KEY: str = Field(default="sk-fake-key", description="OpenAI-compatible API Key")
    LLM_BASE_URL: str = Field(default="https://api.deepseek.com/v1", description="OpenAI-compatible Base URL")
    LLM_MODEL: str = Field(default="deepseek-chat", description="Model Name")
    LLM_TEMPERATURE: float = 0.1

    # 安全沙箱与运维状态机
    READ_ONLY_MODE: bool = True
    MAX_DEEPDIVE_ROUNDS: int = 3
    LOG_TAIL_LINES: int = 100

settings = Settings()
