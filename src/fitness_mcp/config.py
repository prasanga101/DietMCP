from datetime import date
from typing import Literal
from pathlib import Path
from functools import lru_cache
from uuid import UUID
from zoneinfo import ZoneInfo

from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / '.env', override=False)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore', hide_input_in_errors=True, allow_inf_nan=False)
    supabase_url: str
    supabase_server_key: SecretStr
    owner_user_id: UUID
    public_url: str = 'http://localhost:8000'
    github_client_id: str = ''
    github_client_secret: SecretStr = SecretStr('')
    github_owner_id: str = ''
    timezone: str = 'Asia/Kathmandu'
    baseline_kcal: float | None = Field(default=None, gt=0, le=10000)
    birth_date: date
    height_cm: float = Field( gt=0, le=260)
    weight_kg: float = Field( gt=0, le=500)
    target_weight_kg: float = Field( gt=0, le=500)
    sex: Literal['male', 'female']
    baseline_multiplier: float = Field(default=1.2, ge=1, le=2)
    data_dir: Path = ROOT / '.private'
    resend_api_key: SecretStr = SecretStr('')
    email_from: str = ''
    email_to: str = ''
    weekly_email_enabled: bool = False
    report_weekday: int = Field(default=4, ge=0, le=6)  # Friday
    report_hour: int = Field(default=16, ge=0, le=23)
    report_minute: int = Field(default=0, ge=0, le=59)

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        ZoneInfo(value)
        return value

    @field_validator('supabase_url')
    @classmethod
    def valid_supabase(cls, value):
        if not value.startswith('https://'):
            raise ValueError('Supabase URL must use HTTPS')
        return value.rstrip('/')


@lru_cache
def settings():
    return Settings()


def profile_for(day):
    from datetime import date
    cfg = settings()
    birth = cfg.birth_date
    age = day.year - birth.year - ((day.month, day.day) < (birth.month, birth.day))
    if age < 18:
        raise ValueError('Adult energy formula requires age 18 or above.')
    resting = 10 * cfg.weight_kg + 6.25 * cfg.height_cm - 5 * age + (5 if cfg.sex == 'male' else -161)
    baseline = cfg.baseline_kcal if cfg.baseline_kcal is not None else round(resting * cfg.baseline_multiplier, 1)
    return {'age': age, 'height_cm': cfg.height_cm, 'weight_kg': cfg.weight_kg,
            'target_weight_kg': cfg.target_weight_kg, 'resting_kcal': round(resting, 1),
            'baseline_kcal': baseline, 'baseline_multiplier': cfg.baseline_multiplier,
            'method': 'Explicit baseline' if cfg.baseline_kcal is not None else 'Mifflin-St Jeor x baseline multiplier'}
