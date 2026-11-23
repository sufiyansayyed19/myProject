from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    SERVICE_NAME: str = "user-auth-service"
    HOST: str = "0.0.0.0"
    PORT: int = 8001
    DATABASE_URL: str = "postgresql+psycopg://user_auth_user:user_auth_pass@localhost:5432/user_db"

    COMPANY_EMAIL_DOMAIN: str = "company.com"
    OTP_HMAC_SECRET: str = "dev-otp-hmac-secret-change-me"
    OTP_EXPIRE_MINUTES: int = 5
    OTP_MAX_ATTEMPTS: int = 5
    OTP_RESEND_COOLDOWN_SECONDS: int = 60
    EMAIL_SENDER_MODE: str = "console"
    ENVIRONMENT: str = "development"

    JWT_PRIVATE_KEY_PATH: str = "../../keys/jwt_private.pem"
    JWT_PUBLIC_KEY_PATH: str = "../../keys/jwt_public.pem"
    JWT_ISSUER: str = "corporate-parking-auth"
    JWT_AUDIENCE: str = "corporate-parking"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


settings = Settings()
