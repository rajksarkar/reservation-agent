"""Configuration management using Pydantic."""

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


class SMTPConfig(BaseModel):
    """SMTP email configuration."""

    host: str = "smtp.gmail.com"
    port: int = 587
    username: str
    password: str
    from_address: str | None = None
    to_addresses: list[str] = Field(default_factory=list)

    @field_validator("from_address", mode="before")
    @classmethod
    def default_from_address(cls, v: str | None, info) -> str:
        if v is None:
            return info.data.get("username", "")
        return v


class PlatformCredential(BaseModel):
    """Credentials for a reservation platform."""

    platform: Literal["resy", "opentable", "tock"]
    username: str
    password: str


class RestaurantConfig(BaseModel):
    """Configuration for a restaurant to monitor."""

    name: str
    platform: Literal["resy", "opentable", "tock"]
    venue_id: str
    party_size: int = 2
    target_dates: list[str] = Field(default_factory=list)
    preferred_times: list[str] = Field(default_factory=list)
    release_time: str = "09:00"
    release_days_ahead: int = 30
    monitor_cancellations: bool = True
    enabled: bool = True

    @field_validator("target_dates", mode="before")
    @classmethod
    def parse_dates(cls, v):
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("preferred_times", mode="before")
    @classmethod
    def parse_times(cls, v):
        if isinstance(v, str):
            return [v]
        return v


class SchedulerConfig(BaseModel):
    """Scheduler configuration."""

    cancellation_poll_interval: int = 60  # seconds
    snipe_wake_before: int = 30  # seconds before release
    snipe_rapid_poll_interval: float = 0.5  # seconds during snipe window
    snipe_duration: int = 10  # seconds to rapid poll
    max_backoff: int = 300  # max seconds between retries on error


class BrowserConfig(BaseModel):
    """Browser automation configuration."""

    headless: bool = True
    slow_mo: int = 0  # milliseconds
    timeout: int = 30000  # milliseconds
    sessions_dir: str = "data/sessions"


class AgentConfig(BaseModel):
    """Main agent configuration."""

    smtp: SMTPConfig
    credentials: list[PlatformCredential] = Field(default_factory=list)
    restaurants: list[RestaurantConfig] = Field(default_factory=list)
    scheduler: SchedulerConfig = Field(default_factory=SchedulerConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    database_url: str = "sqlite+aiosqlite:///data/reservation_agent.db"
    log_level: str = "INFO"
    log_dir: str = "data/logs"
    dry_run: bool = False

    def get_credential(self, platform: str) -> PlatformCredential | None:
        """Get credentials for a specific platform."""
        for cred in self.credentials:
            if cred.platform == platform:
                return cred
        return None


def expand_env_vars(value: str) -> str:
    """Expand environment variables in a string (${VAR} or $VAR format)."""
    pattern = r"\$\{([^}]+)\}|\$([A-Za-z_][A-Za-z0-9_]*)"

    def replacer(match):
        var_name = match.group(1) or match.group(2)
        return os.environ.get(var_name, match.group(0))

    return re.sub(pattern, replacer, value)


def process_env_vars(obj):
    """Recursively process environment variables in a dictionary or list."""
    if isinstance(obj, dict):
        return {k: process_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [process_env_vars(item) for item in obj]
    elif isinstance(obj, str):
        return expand_env_vars(obj)
    return obj


def load_config(config_path: str | Path | None = None) -> AgentConfig:
    """Load configuration from YAML file."""
    if config_path is None:
        # Look for config in standard locations
        search_paths = [
            Path("config/config.yaml"),
            Path("config.yaml"),
            Path.home() / ".config" / "reservation-agent" / "config.yaml",
        ]
        for path in search_paths:
            if path.exists():
                config_path = path
                break
        else:
            raise FileNotFoundError(
                "No configuration file found. Create config/config.yaml or specify path."
            )

    config_path = Path(config_path)
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")

    with open(config_path) as f:
        raw_config = yaml.safe_load(f)

    # Process environment variables
    config_data = process_env_vars(raw_config)

    return AgentConfig(**config_data)


class Settings(BaseSettings):
    """Environment-based settings (optional override)."""

    config_path: str | None = None
    dry_run: bool = False
    log_level: str = "INFO"

    class Config:
        env_prefix = "RESERVATION_AGENT_"
