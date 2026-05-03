from __future__ import annotations

from fastapi import Header, HTTPException, status

from .config import Settings


def make_api_key_dep(settings: Settings):
    def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
        if not x_api_key or x_api_key != settings.api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid or missing X-API-Key",
            )
    return require_api_key
