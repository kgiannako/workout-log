from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.storage import LocalStorage, S3Storage


def _settings(tmp_path) -> Settings:
    return Settings(
        storage_backend="local",
        api_key="test-key",
        s3_bucket=None,
        aws_region=None,
        local_data_dir=str(tmp_path),
    )


@pytest.fixture
def client(tmp_path):
    settings = _settings(tmp_path)
    storage = LocalStorage(settings.local_data_dir)
    app = create_app(settings=settings, storage=storage)
    c = TestClient(app)
    c.headers.update({"X-API-Key": "test-key"})
    return c


def _strength_payload(d: str = "2026-05-03", name: str = "bench press") -> dict:
    return {
        "date": d,
        "exercises": [
            {"name": name, "sets": [{"reps": 5, "weight_kg": 80}, {"reps": 5, "weight_kg": 80}]}
        ],
    }


def _cardio_payload(d: str = "2026-05-04", name: str = "morning run") -> dict:
    return {
        "date": d,
        "exercises": [{"name": name, "distance_km": 5.0, "duration_seconds": 1500}],
    }


def test_healthz_no_auth(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings=settings, storage=LocalStorage(str(tmp_path)))
    c = TestClient(app)
    r = c.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_missing_api_key_returns_401(tmp_path):
    settings = _settings(tmp_path)
    app = create_app(settings=settings, storage=LocalStorage(str(tmp_path)))
    c = TestClient(app)
    assert c.get("/workouts").status_code == 401
    assert c.get("/workouts", headers={"X-API-Key": "wrong"}).status_code == 401


def test_log_then_fetch_strength(client):
    r = client.post("/workouts", json=_strength_payload())
    assert r.status_code == 201, r.text
    body = r.json()
    workout_id = body["id"]
    assert body["date"] == "2026-05-03"
    assert body["exercises"][0]["sets"][0]["weight_kg"] == 80

    r = client.get(f"/workouts/{workout_id}")
    assert r.status_code == 200
    assert r.json()["id"] == workout_id


def test_filter_by_exercise_name(client):
    client.post("/workouts", json=_strength_payload(name="bench press"))
    client.post("/workouts", json=_cardio_payload(name="morning run"))

    r = client.get("/workouts", params={"exercise": "run"})
    assert r.status_code == 200
    names = [w["exercises"][0]["name"] for w in r.json()]
    assert names == ["morning run"]


def test_filter_by_date_range(client):
    client.post("/workouts", json=_strength_payload(d="2026-04-01"))
    client.post("/workouts", json=_strength_payload(d="2026-05-15"))
    client.post("/workouts", json=_strength_payload(d="2026-06-01"))

    r = client.get("/workouts", params={"start": "2026-05-01", "end": "2026-05-31"})
    assert r.status_code == 200
    dates = [w["date"] for w in r.json()]
    assert dates == ["2026-05-15"]


def test_single_date_filter(client):
    client.post("/workouts", json=_strength_payload(d="2026-05-03"))
    client.post("/workouts", json=_strength_payload(d="2026-05-04"))
    r = client.get("/workouts", params={"date": "2026-05-04"})
    assert [w["date"] for w in r.json()] == ["2026-05-04"]


def test_weekly_stats_arithmetic(client):
    # 2026-05-03 is a Sunday; ISO week containing it is Mon 2026-04-27..Sun 2026-05-03
    client.post("/workouts", json=_strength_payload(d="2026-04-28"))  # 2x5x80 = 800
    client.post("/workouts", json=_cardio_payload(d="2026-05-02"))    # 5km, 1500s
    client.post("/workouts", json=_strength_payload(d="2026-05-04"))  # next week, ignored

    r = client.get("/stats/weekly", params={"week_of": "2026-05-03"})
    assert r.status_code == 200
    body = r.json()
    assert body["period_start"] == "2026-04-27"
    assert body["period_end"] == "2026-05-03"
    assert body["workout_count"] == 2
    assert body["total_volume_kg"] == 800
    assert body["total_distance_km"] == 5.0
    assert body["total_duration_seconds"] == 1500
    assert body["by_exercise"]["bench press"]["sets"] == 2
    assert body["by_exercise"]["bench press"]["reps"] == 10


def test_monthly_stats(client):
    client.post("/workouts", json=_strength_payload(d="2026-05-01"))
    client.post("/workouts", json=_strength_payload(d="2026-05-31"))
    client.post("/workouts", json=_strength_payload(d="2026-06-01"))

    r = client.get("/stats/monthly", params={"month": "2026-05"})
    assert r.status_code == 200
    body = r.json()
    assert body["period_start"] == "2026-05-01"
    assert body["period_end"] == "2026-05-31"
    assert body["workout_count"] == 2


def test_exercise_without_metrics_rejected(client):
    bad = {"date": "2026-05-03", "exercises": [{"name": "shrug"}]}
    r = client.post("/workouts", json=bad)
    assert r.status_code == 422


def test_delete_workout(client):
    r = client.post("/workouts", json=_strength_payload())
    workout_id = r.json()["id"]
    assert client.delete(f"/workouts/{workout_id}").status_code == 204
    assert client.get(f"/workouts/{workout_id}").status_code == 404
    assert client.delete(f"/workouts/{workout_id}").status_code == 404


# ----- S3 backend via moto ------------------------------------------------------


@pytest.fixture
def s3_storage(monkeypatch):
    pytest.importorskip("moto")
    from moto import mock_aws
    import boto3

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")

    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="test-bucket")
        yield S3Storage(bucket="test-bucket", client=client)


def test_s3_round_trip(s3_storage):
    settings = Settings(
        storage_backend="s3",
        api_key="test-key",
        s3_bucket="test-bucket",
        aws_region="us-east-1",
        local_data_dir="/tmp/unused",
    )
    app = create_app(settings=settings, storage=s3_storage)
    c = TestClient(app)
    c.headers.update({"X-API-Key": "test-key"})

    r = c.post("/workouts", json=_strength_payload())
    assert r.status_code == 201
    workout_id = r.json()["id"]

    r = c.get(f"/workouts/{workout_id}")
    assert r.status_code == 200
    assert r.json()["id"] == workout_id

    r = c.get("/workouts", params={"exercise": "bench"})
    assert len(r.json()) == 1

    assert c.delete(f"/workouts/{workout_id}").status_code == 204
    assert c.get(f"/workouts/{workout_id}").status_code == 404
