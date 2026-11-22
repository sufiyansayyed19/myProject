from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "parking-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8003
    DATABASE_URL: str = "postgresql+psycopg://parking_user:parking_pass@localhost:5432/parking_db"

    BUSINESS_TIMEZONE: str = "Asia/Kolkata"

    JWT_PUBLIC_KEY_PATH: str = "../../keys/jwt_public.pem"
    JWT_ISSUER: str = "corporate-parking-auth"
    JWT_AUDIENCE: str = "corporate-parking"

    VEHICLE_SERVICE_URL: str = "http://127.0.0.1:8002"
    PAYMENT_SERVICE_URL: str = "http://127.0.0.1:8004"
    PARKING_TO_VEHICLE_TOKEN: str = "dev-parking-to-vehicle-token"
    PARKING_TO_PAYMENT_TOKEN: str = "dev-parking-to-payment-token"
    PAYMENT_TO_PARKING_TOKEN: str = "dev-payment-to-parking-token"
    VEHICLE_TO_PARKING_TOKEN: str = "dev-vehicle-to-parking-token"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
