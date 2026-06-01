"""Configuration for the object-store client.

Read from environment variables following the ``os.getenv``-with-default style
used in :mod:`doci.globals`.
"""

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True, slots=True)
class ObjStoreConfig:
    """Connection + presigning configuration for an :class:`ObjStore`."""

    endpoint_url: str | None = None
    public_endpoint_url: str | None = None
    region: str = "us-east-1"
    access_key_id: str | None = None
    secret_access_key: str | None = None
    bucket: str | None = None
    presign_expiry: int = 900
    force_path_style: bool = True

    @classmethod
    def from_env(cls) -> "ObjStoreConfig":
        """Build a config from ``S3_*`` / ``AWS_*`` environment variables."""
        return cls(
            endpoint_url=os.getenv("S3_ENDPOINT_URL"),
            public_endpoint_url=os.getenv("S3_PUBLIC_ENDPOINT_URL"),
            region=os.getenv("S3_REGION") or os.getenv("AWS_REGION") or "us-east-1",
            access_key_id=os.getenv("S3_ACCESS_KEY_ID"),
            secret_access_key=os.getenv("S3_SECRET_ACCESS_KEY"),
            bucket=os.getenv("S3_BUCKET"),
            presign_expiry=int(os.getenv("S3_PRESIGN_EXPIRY", "900")),
            force_path_style=_env_bool("S3_FORCE_PATH_STYLE", True),
        )
