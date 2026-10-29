from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "IMARA-CARE API"
    environment: str = "development"
    database_url: str = "sqlite:///./imara-care.db"
    facility_name: str = "Imara Care Clinic"
    facility_code: str = "IM"
    frontend_origin: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
