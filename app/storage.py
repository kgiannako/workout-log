from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Protocol
from uuid import UUID

from .models import Workout


class WorkoutStorage(Protocol):
    def put(self, w: Workout) -> None: ...
    def get(self, workout_id: UUID) -> Workout | None: ...
    def delete(self, workout_id: UUID) -> bool: ...
    def list(
        self, start: date | None = None, end: date | None = None
    ) -> Iterable[Workout]: ...


def _serialize(w: Workout) -> str:
    return w.model_dump_json()


def _deserialize(blob: str | bytes) -> Workout:
    if isinstance(blob, bytes):
        blob = blob.decode("utf-8")
    return Workout.model_validate_json(blob)


def _in_range(d: date, start: date | None, end: date | None) -> bool:
    if start is not None and d < start:
        return False
    if end is not None and d > end:
        return False
    return True


# ----- Local filesystem backend -------------------------------------------------


class LocalStorage:
    """Stores workouts as ./<root>/workouts/<YYYY-MM-DD>/<id>.json."""

    def __init__(self, root: str | os.PathLike[str]):
        self.root = Path(root)
        (self.root / "workouts").mkdir(parents=True, exist_ok=True)
        (self.root / "index").mkdir(parents=True, exist_ok=True)

    def _workout_path(self, d: date, workout_id: UUID) -> Path:
        return self.root / "workouts" / d.isoformat() / f"{workout_id}.json"

    def _index_path(self, workout_id: UUID) -> Path:
        return self.root / "index" / f"{workout_id}.txt"

    def put(self, w: Workout) -> None:
        path = self._workout_path(w.date, w.id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_serialize(w), encoding="utf-8")
        self._index_path(w.id).write_text(w.date.isoformat(), encoding="utf-8")

    def _resolve_date(self, workout_id: UUID) -> date | None:
        idx = self._index_path(workout_id)
        if not idx.exists():
            return None
        return date.fromisoformat(idx.read_text(encoding="utf-8").strip())

    def get(self, workout_id: UUID) -> Workout | None:
        d = self._resolve_date(workout_id)
        if d is None:
            return None
        path = self._workout_path(d, workout_id)
        if not path.exists():
            return None
        return _deserialize(path.read_bytes())

    def delete(self, workout_id: UUID) -> bool:
        d = self._resolve_date(workout_id)
        if d is None:
            return False
        path = self._workout_path(d, workout_id)
        existed = path.exists()
        if existed:
            path.unlink()
        self._index_path(workout_id).unlink(missing_ok=True)
        return existed

    def list(
        self, start: date | None = None, end: date | None = None
    ) -> Iterator[Workout]:
        wroot = self.root / "workouts"
        if not wroot.exists():
            return
        for date_dir in sorted(wroot.iterdir()):
            if not date_dir.is_dir():
                continue
            try:
                d = date.fromisoformat(date_dir.name)
            except ValueError:
                continue
            if not _in_range(d, start, end):
                continue
            for f in sorted(date_dir.glob("*.json")):
                yield _deserialize(f.read_bytes())


# ----- S3 backend ---------------------------------------------------------------


class S3Storage:
    """Keys: workouts/<YYYY-MM-DD>/<id>.json and index/<id>.txt -> 'YYYY-MM-DD'."""

    def __init__(self, bucket: str, region: str | None = None, client=None):
        if client is None:
            import boto3  # imported lazily so tests don't need boto for Local

            client = boto3.client("s3", region_name=region)
        self.bucket = bucket
        self.client = client

    def _workout_key(self, d: date, workout_id: UUID) -> str:
        return f"workouts/{d.isoformat()}/{workout_id}.json"

    def _index_key(self, workout_id: UUID) -> str:
        return f"index/{workout_id}.txt"

    def put(self, w: Workout) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._workout_key(w.date, w.id),
            Body=_serialize(w).encode("utf-8"),
            ContentType="application/json",
        )
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._index_key(w.id),
            Body=w.date.isoformat().encode("utf-8"),
            ContentType="text/plain",
        )

    def _resolve_date(self, workout_id: UUID) -> date | None:
        try:
            obj = self.client.get_object(
                Bucket=self.bucket, Key=self._index_key(workout_id)
            )
        except self.client.exceptions.NoSuchKey:
            return None
        except Exception as exc:  # botocore ClientError 404
            if getattr(exc, "response", {}).get("Error", {}).get("Code") in {
                "NoSuchKey",
                "404",
            }:
                return None
            raise
        return date.fromisoformat(obj["Body"].read().decode("utf-8").strip())

    def get(self, workout_id: UUID) -> Workout | None:
        d = self._resolve_date(workout_id)
        if d is None:
            return None
        try:
            obj = self.client.get_object(
                Bucket=self.bucket, Key=self._workout_key(d, workout_id)
            )
        except self.client.exceptions.NoSuchKey:
            return None
        return _deserialize(obj["Body"].read())

    def delete(self, workout_id: UUID) -> bool:
        d = self._resolve_date(workout_id)
        if d is None:
            return False
        self.client.delete_object(
            Bucket=self.bucket, Key=self._workout_key(d, workout_id)
        )
        self.client.delete_object(Bucket=self.bucket, Key=self._index_key(workout_id))
        return True

    def list(
        self, start: date | None = None, end: date | None = None
    ) -> Iterator[Workout]:
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix="workouts/"):
            for entry in page.get("Contents", []) or []:
                key: str = entry["Key"]
                # key = workouts/<YYYY-MM-DD>/<id>.json
                parts = key.split("/")
                if len(parts) != 3:
                    continue
                try:
                    d = date.fromisoformat(parts[1])
                except ValueError:
                    continue
                if not _in_range(d, start, end):
                    continue
                obj = self.client.get_object(Bucket=self.bucket, Key=key)
                yield _deserialize(obj["Body"].read())


def build_storage(settings) -> WorkoutStorage:
    if settings.storage_backend == "s3":
        return S3Storage(bucket=settings.s3_bucket, region=settings.aws_region)
    return LocalStorage(settings.local_data_dir)
