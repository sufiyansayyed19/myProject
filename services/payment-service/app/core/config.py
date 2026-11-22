from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "payment-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8004
    DATABASE_URL: str = "postgresql+psycopg://payment_user:payment_pass@localhost:5432/payment_db"

    JWT_PUBLIC_KEY_PATH: str = "../../keys/jwt_public.pem"
    JWT_ISSUER: str = "corporate-parking-auth"
    JWT_AUDIENCE: str = "corporate-parking"

    PARKING_SERVICE_URL: str = "http://127.0.0.1:8003"
    PARKING_TO_PAYMENT_TOKEN: str = "dev-parking-to-payment-token"
    PAYMENT_TO_PARKING_TOKEN: str = "dev-payment-to-parking-token"

    PAYMENT_SIMULATION_DEFAULT_OUTCOME: str = "SUCCESS"
    ENABLE_TEST_PAYMENT_OVERRIDE: bool = True
    ENVIRONMENT: str = "development"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
