from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    kite_api_key: str = ""
    kite_api_secret: str = ""
    session_file: str = ".kite_session.json"
    state_file: str = "trade_state.json"

    # Kite requires market protection on MARKET orders; -1 lets Kite pick it.
    market_protection: int = -1
    # Exchange freeze limits (units). Bigger orders are split into slices.
    freeze_qty_nifty: int = 1800
    freeze_qty_sensex: int = 1000

    tick_seconds: float = 1.0
    chain_width: int = 40  # strikes each side of ATM offered in the strike dropdowns


settings = Settings()
