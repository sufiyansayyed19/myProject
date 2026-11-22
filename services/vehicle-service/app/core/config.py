from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "vehicle-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8002
    DATABASE_URL: str = "postgresql+psycopg://vehicle_user:vehicle_pass@localhost:5432/vehicle_db"

    JWT_PUBLIC_KEY_PATH: str = "../../keys/jwt_public.pem"
    JWT_ISSUER: str = "corporate-parking-auth"
    JWT_AUDIENCE: str = "corporate-parking"

    PARKING_SERVICE_URL: str = "http://127.0.0.1:8003"
    PARKING_TO_VEHICLE_TOKEN: str = "dev-parking-to-vehicle-token"
    VEHICLE_TO_PARKING_TOKEN: str = "dev-vehicle-to-parking-token"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
