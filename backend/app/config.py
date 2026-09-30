from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kite_api_key: str = ""
    kite_api_secret: str = ""
    # Where the daily Kite access token is cached between restarts.
    session_file: str = ".kite_session.json"
    # Serve sample positions instead of calling Kite (no API keys needed).
    demo_mode: bool = False
    frontend_url: str = "http://localhost:3000"

    risk_free_rate: float = 0.065
    refresh_seconds: float = 2.0

    # Risk limits (rupees / units of underlying).
    max_portfolio_loss: float = 50_000
    max_loss_per_underlying: float = 25_000
    max_abs_delta_per_underlying: float = 150
    premium_multiple_alert: float = 2.0
    breach_buffer_pct: float = 0.5


settings = Settings()
