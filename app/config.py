from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "IMARA-CARE API"
    environment: str = "development"
    database_url: str = "sqlite:///./imara-care.db"
    facility_name: str = "Imara Care Clinic"
    facility_code: str = "IM"
    frontend_origin: str = "http://localhost:3000"
    auth_issuer: str = "http://localhost:3000"
    auth_jwks_url: str = "http://localhost:3000/api/auth/jwks"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
