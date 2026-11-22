from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "api-gateway"
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    CORS_ALLOW_ORIGINS: str = "http://localhost:3000,http://localhost:5173"

    USER_AUTH_SERVICE_URL: str = "http://127.0.0.1:8001"
    VEHICLE_SERVICE_URL: str = "http://127.0.0.1:8002"
    PARKING_SERVICE_URL: str = "http://127.0.0.1:8003"
    PAYMENT_SERVICE_URL: str = "http://127.0.0.1:8004"

    JWT_PUBLIC_KEY_PATH: str = "keys/jwt_public.pem"
    JWT_ISSUER: str = "corporate-parking-auth"
    JWT_AUDIENCE: str = "corporate-parking"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]


settings = Settings()
