from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./cashbook.db"
    jwt_secret: str = "dev-only-secret-change-me-in-production-0000"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 12

    # Channels and currencies are configuration, not code changes.
    channels: list[str] = [
        "Booking.com", "Hostelworld", "Trip.com", "Agoda",
        "ETG", "Airbnb", "Walk-in", "Direct",
    ]
    currencies: list[str] = ["AMD", "USD", "EUR", "RUB"]
    base_currency: str = "AMD"

    # Differences below this many base-currency units count as balanced.
    tolerance: int = 1


settings = Settings()
