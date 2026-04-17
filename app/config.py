from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(slots=True)
class Settings:
    app_title: str = os.getenv("APP_TITLE", "BYD Web Console")
    host: str = os.getenv("HOST", "0.0.0.0")
    port: int = int(os.getenv("PORT", "8010"))
    debug: bool = _env_bool("DEBUG", False)
    timezone_name: str = os.getenv("TIMEZONE", "Australia/Melbourne")
    byd_username: str = os.getenv("BYD_USERNAME", "")
    byd_password: str = os.getenv("BYD_PASSWORD", "")
    byd_vin: str = os.getenv("BYD_VIN", "")
    byd_control_pin: str = os.getenv("BYD_CONTROL_PIN", "")
    byd_time_zone: str = os.getenv("BYD_TIME_ZONE", "")
    google_maps_api_key: str = os.getenv("GOOGLE_MAPS_API_KEY", "")
    session_secret: str = os.getenv("SESSION_SECRET", "change-me")
    base_dir: Path = Path(__file__).resolve().parents[1]


settings = Settings()
