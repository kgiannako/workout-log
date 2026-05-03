from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, model_validator


class StrengthSet(BaseModel):
    reps: int = Field(gt=0)
    weight_kg: float = Field(ge=0)


class Exercise(BaseModel):
    name: str = Field(min_length=1)
    sets: list[StrengthSet] | None = None
    distance_km: float | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _at_least_one_metric(self) -> "Exercise":
        if not self.sets and self.distance_km is None and self.duration_seconds is None:
            raise ValueError(
                "exercise must have either 'sets' or 'distance_km'/'duration_seconds'"
            )
        return self


class WorkoutCreate(BaseModel):
    date: date
    exercises: list[Exercise] = Field(min_length=1)
    notes: str | None = None


class Workout(WorkoutCreate):
    id: UUID = Field(default_factory=uuid4)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ExerciseStats(BaseModel):
    sets: int = 0
    reps: int = 0
    volume_kg: float = 0.0
    distance_km: float = 0.0
    duration_seconds: int = 0


class StatsResponse(BaseModel):
    period_start: date
    period_end: date
    workout_count: int
    total_volume_kg: float
    total_distance_km: float
    total_duration_seconds: int
    by_exercise: dict[str, ExerciseStats]
