from datetime import date
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Food(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    entry_id: UUID
    log_date: date
    food_name: str = Field(min_length=1, max_length=250)
    meal_type: Literal['breakfast', 'lunch', 'dinner', 'snack', 'other'] = 'other'
    quantity: float | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=40)
    calories_kcal: float | None = Field(default=None, ge=0, le=20000)
    protein_g: float | None = Field(default=None, ge=0, le=2000)
    carbs_g: float | None = Field(default=None, ge=0, le=5000)
    fat_g: float | None = Field(default=None, ge=0, le=2000)
    notes: str = Field(default='', max_length=2000)


class Activity(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    entry_id: UUID
    log_date: date
    activity_type: str = Field(min_length=1, max_length=250)
    duration_minutes: float | None = Field(default=None, ge=0, le=1440)
    steps: int | None = Field(default=None, ge=0, le=200000)
    distance_km: float | None = Field(default=None, ge=0, le=1000)
    incline_percent: float | None = Field(default=None, ge=0, le=100)
    speed_kmh: float | None = Field(default=None, ge=0, le=100)
    estimated_calories_kcal: float | None = Field(default=None, ge=0, le=20000)
    intensity: Literal['light', 'moderate', 'vigorous'] | None = None
    notes: str = Field(default='', max_length=2000)
