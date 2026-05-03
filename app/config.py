from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    storage_backend: str       # "s3" or "local"
    api_key: str
    s3_bucket: str | None
    aws_region: str | None
    local_data_dir: str


def load_settings() -> Settings:
    backend = os.environ.get("STORAGE_BACKEND", "local").lower()
    if backend not in {"s3", "local"}:
        raise RuntimeError(f"invalid STORAGE_BACKEND: {backend!r}")

    api_key = os.environ.get("API_KEY", "")
    if not api_key:
        # Allow empty in local dev only — but require for s3.
        if backend == "s3":
            raise RuntimeError("API_KEY env var is required when STORAGE_BACKEND=s3")
        api_key = "dev"

    s3_bucket = os.environ.get("S3_BUCKET")
    if backend == "s3" and not s3_bucket:
        raise RuntimeError("S3_BUCKET env var is required when STORAGE_BACKEND=s3")

    return Settings(
        storage_backend=backend,
        api_key=api_key,
        s3_bucket=s3_bucket,
        aws_region=os.environ.get("AWS_REGION"),
        local_data_dir=os.environ.get("LOCAL_DATA_DIR", "./.data"),
    )
