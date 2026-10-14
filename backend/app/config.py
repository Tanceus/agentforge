from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AgentForge"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://agentforge:agentforge@localhost:5432/agentforge"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    refresh_token_days: int = 7
    llm_provider: str = "mock"
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"
    llm_timeout_seconds: float = 30.0
    cors_origins: str = "http://localhost:5173,http://localhost:8080"
    rate_limit_per_minute: int = 120
    task_rate_limit_per_minute: int = 30
    login_rate_limit_per_minute: int = 20
    retry_base_seconds: float = 1.0
    retry_max_seconds: float = 60.0
    seed_demo: bool = True
    demo_user_email: str = "demo@example.com"
    demo_user_password: str = "DemoPass123!"
    admin_user_email: str = "admin@example.com"
    admin_user_password: str = "AdminPass123!"
    trust_proxy: bool = False
    max_request_bytes: int = 1_000_000
    worker_metrics_port: int = 9100
    http_tool_timeout_seconds: float = 10.0
    http_tool_max_bytes: int = 200_000
    max_agent_steps: int = 8
    dashboard_cache_seconds: int = 5
    worker_heartbeat_seconds: int = 15

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    @property
    def refresh_token_seconds(self) -> int:
        return self.refresh_token_days * 24 * 60 * 60


WEAK_SECRETS = {
    "change-me",
    "change-me-in-production",
    "dev-only-change-me-agentforge-secret",
}


def validate_runtime_settings(settings: Settings) -> None:
    if settings.environment == "production":
        if settings.jwt_secret in WEAK_SECRETS or len(settings.jwt_secret) < 32:
            raise RuntimeError("JWT_SECRET must be a unique value of at least 32 characters in production")
        if settings.seed_demo and settings.demo_user_password == "DemoPass123!":
            raise RuntimeError("Refusing to seed default demo passwords when ENVIRONMENT=production")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    validate_runtime_settings(settings)
    return settings
