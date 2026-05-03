from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable

from .models import ExerciseStats, StatsResponse, Workout


def week_bounds(any_day: date) -> tuple[date, date]:
    """ISO week (Mon-Sun) containing `any_day`."""
    start = any_day - timedelta(days=any_day.weekday())
    end = start + timedelta(days=6)
    return start, end


def month_bounds(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    if month == 12:
        next_month_start = date(year + 1, 1, 1)
    else:
        next_month_start = date(year, month + 1, 1)
    end = next_month_start - timedelta(days=1)
    return start, end


def aggregate(
    workouts: Iterable[Workout], period_start: date, period_end: date
) -> StatsResponse:
    workout_count = 0
    total_volume = 0.0
    total_distance = 0.0
    total_duration = 0
    by_exercise: dict[str, ExerciseStats] = {}

    for w in workouts:
        if w.date < period_start or w.date > period_end:
            continue
        workout_count += 1
        for ex in w.exercises:
            key = ex.name.strip().lower()
            agg = by_exercise.setdefault(key, ExerciseStats())
            if ex.sets:
                for s in ex.sets:
                    vol = s.reps * s.weight_kg
                    agg.sets += 1
                    agg.reps += s.reps
                    agg.volume_kg += vol
                    total_volume += vol
            if ex.distance_km:
                agg.distance_km += ex.distance_km
                total_distance += ex.distance_km
            if ex.duration_seconds:
                agg.duration_seconds += ex.duration_seconds
                total_duration += ex.duration_seconds

    return StatsResponse(
        period_start=period_start,
        period_end=period_end,
        workout_count=workout_count,
        total_volume_kg=round(total_volume, 4),
        total_distance_km=round(total_distance, 4),
        total_duration_seconds=total_duration,
        by_exercise=by_exercise,
    )
