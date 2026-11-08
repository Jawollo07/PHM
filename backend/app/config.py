from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "PHM"
    app_env: str = "development"
    database_url: str = "postgresql+asyncpg://phm:change-me@localhost:5432/phm"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
