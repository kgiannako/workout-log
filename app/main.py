from __future__ import annotations

from datetime import date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Query, Response, status

from .auth import make_api_key_dep
from .config import Settings, load_settings
from .models import StatsResponse, Workout, WorkoutCreate
from .stats import aggregate, month_bounds, week_bounds
from .storage import WorkoutStorage, build_storage


def create_app(
    settings: Settings | None = None,
    storage: WorkoutStorage | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    storage = storage or build_storage(settings)

    app = FastAPI(title="workout-log", version="1.0.0")
    require_key = make_api_key_dep(settings)
    Auth = Depends(require_key)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post(
        "/workouts",
        response_model=Workout,
        status_code=status.HTTP_201_CREATED,
        dependencies=[Auth],
    )
    def log_workout(payload: WorkoutCreate) -> Workout:
        w = Workout(**payload.model_dump())
        storage.put(w)
        return w

    @app.get("/workouts", response_model=list[Workout], dependencies=[Auth])
    def list_workouts(
        date_filter: Annotated[date | None, Query(alias="date")] = None,
        start: date | None = None,
        end: date | None = None,
        exercise: str | None = None,
    ) -> list[Workout]:
        if date_filter is not None:
            start = end = date_filter
        results = list(storage.list(start=start, end=end))
        if exercise:
            needle = exercise.strip().lower()
            results = [
                w for w in results
                if any(needle in ex.name.lower() for ex in w.exercises)
            ]
        results.sort(key=lambda w: (w.date, w.created_at))
        return results

    @app.get("/workouts/{workout_id}", response_model=Workout, dependencies=[Auth])
    def get_workout(workout_id: UUID) -> Workout:
        w = storage.get(workout_id)
        if w is None:
            raise HTTPException(status_code=404, detail="workout not found")
        return w

    @app.delete(
        "/workouts/{workout_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        dependencies=[Auth],
    )
    def delete_workout(workout_id: UUID) -> Response:
        if not storage.delete(workout_id):
            raise HTTPException(status_code=404, detail="workout not found")
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.get("/stats/weekly", response_model=StatsResponse, dependencies=[Auth])
    def stats_weekly(week_of: date | None = None) -> StatsResponse:
        anchor = week_of or datetime.utcnow().date()
        start, end = week_bounds(anchor)
        return aggregate(storage.list(start=start, end=end), start, end)

    @app.get("/stats/monthly", response_model=StatsResponse, dependencies=[Auth])
    def stats_monthly(
        month: Annotated[
            str | None,
            Query(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM"),
        ] = None,
    ) -> StatsResponse:
        if month is None:
            today = datetime.utcnow().date()
            year, month_n = today.year, today.month
        else:
            year, month_n = (int(p) for p in month.split("-"))
            if not (1 <= month_n <= 12):
                raise HTTPException(status_code=422, detail="invalid month")
        start, end = month_bounds(year, month_n)
        return aggregate(storage.list(start=start, end=end), start, end)

    return app


# Module-level app + Lambda handler.
app = create_app()

try:
    from mangum import Mangum
    handler = Mangum(app, lifespan="off")
except ImportError:  # mangum not installed in some local-only environments
    handler = None
