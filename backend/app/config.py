"""Application settings (environment-driven via pydantic-settings)."""

import datetime as dt
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]

ProviderName = Literal["claude_code", "gemini", "anthropic", "replay"]


class ImpactParams(BaseSettings):
    """Synthetic business-impact assumptions (shown labelled as such in the UI)."""

    manual_employee_min: float = 12.0
    manual_finance_min: float = 6.0
    agent_employee_min: float = 2.5
    agent_finance_min: float = 1.5
    finance_inr_per_hour: float = 600.0
    employee_inr_per_hour: float = 900.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    LLM_PROVIDER: ProviderName = "replay"
    LLM_RECORD: bool = False
    LLM_MAX_CONCURRENCY: int = 3
    LLM_TIMEOUT_S: float = 120.0

    CLAUDE_CODE_MODEL: str = "sonnet"
    CLAUDE_CODE_BIN: str = "claude"
    GEMINI_API_KEY: str | None = None
    GEMINI_MODEL: str = "gemini-2.5-flash"
    ANTHROPIC_API_KEY: str | None = None
    ANTHROPIC_MODEL: str = "claude-sonnet-5-5"
    ANTHROPIC_EFFORT: Literal["low", "medium", "high"] = "medium"

    PROMPT_VERSION_EXTRACT: str | None = None
    PROMPT_VERSION_COMPILE: str | None = None

    DATA_DIR: Path = REPO_ROOT / "data"
    DATABASE_URL: str = f"sqlite:///{REPO_ROOT / 'data' / 'app.db'}"
    ADMIN_TOKEN: str | None = None
    SEED_DEMO: bool = False
    # Replay mode pins the calendar here so the recorded Oct 2026 receipts never age into late-submission
    # findings; live providers always use the real date. Empty to use the real date in replay too.
    DEMO_TODAY: dt.date | None = dt.date(2026, 10, 10)
    REPLAY_DELAY_S: float = 0.0  # pause per replayed LLM call, for recording the demo
    GIT_SHA: str | None = None

    TAU: float = 0.75
    MAX_QUESTIONS_PER_ROUND: int = 3
    DEDUPE_WINDOW_DAYS: int = 90
    FX_USD_INR: float = 84.0
    FINANCE_DECISION_DELAY_S: float = 20.0
    FINANCE_SEED: int = 7
    MAX_UPLOAD_MB: int = 10
    MAX_FILES_PER_REQUEST: int = 10

    impact: ImpactParams = Field(default_factory=ImpactParams)

    @property
    def uploads_dir(self) -> Path:
        return self.DATA_DIR / "uploads"

    @property
    def replay_dir(self) -> Path:
        return self.DATA_DIR / "replay"

    @property
    def demo_dir(self) -> Path:
        return self.DATA_DIR / "demo_receipts"

    @property
    def rulesets_dir(self) -> Path:
        return self.DATA_DIR / "rulesets"

    @property
    def policies_dir(self) -> Path:
        return self.DATA_DIR / "policies"


@lru_cache
def get_settings() -> Settings:
    return Settings()
