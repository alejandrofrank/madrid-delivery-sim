from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Local startup must not implicitly import old cloud credentials/provider settings.
    model_config = SettingsConfigDict(env_file=None, extra="ignore")
    app_port: int = 8010
    database_url: str = "postgresql://delivery:delivery_local_only@127.0.0.1:55432/delivery"
    redis_url: str = "redis://127.0.0.1:56379/0"
    llm_provider: str = "disabled"
    llm_model: str = "gemini-2.5-flash-lite"
    gemini_api_key: str = ""
    google_cloud_project: str = ""
    google_cloud_location: str = "global"
    google_credentials_json: str = ""
    llm_max_calls: int = 4
    llm_max_tokens: int = 12000
    llm_budget_usd: float = 0.02
    llm_input_usd_per_million: float = 0.5
    llm_output_usd_per_million: float = 2.0


@lru_cache
def settings() -> Settings:
    return Settings()
