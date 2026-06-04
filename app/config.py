from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Server
    port: int = 8000
    host: str = "127.0.0.1"
    persist: bool = False
    auto_open_browser: bool = True
    log_level: str = "WARNING"

    # LLM defaults (used when per-conversation values are absent)
    max_tokens: int = 4096
    temperature: float = 0.7


settings = Settings()
