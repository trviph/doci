"""Configuration for the media service."""

import os
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class MediaConfig:
    """Tunables for upload/finalize/view and listing/deletion."""

    max_size: int = 32 << 20  # 32 MiB
    upload_expiry: int = 900  # 15 min
    view_expiry: int = 3600  # 1 h
    view_cache_ttl: int = 3600 * 9 // 10  # 90% of view_expiry
    concurrency: int = 10  # parallel presign fan-out
    purge_after: int = 7 * 24 * 3600  # 7 days
    page_size: int = 50
    max_page_size: int = 100
    delete_max_depth: int = 5

    @classmethod
    def from_env(cls) -> "MediaConfig":
        view_expiry = int(os.getenv("MEDIA_VIEW_EXPIRY", "3600"))
        view_cache_ttl = os.getenv("MEDIA_VIEW_CACHE_TTL")
        return cls(
            max_size=int(os.getenv("MEDIA_MAX_SIZE", str(32 << 20))),
            upload_expiry=int(os.getenv("MEDIA_UPLOAD_EXPIRY", "900")),
            view_expiry=view_expiry,
            view_cache_ttl=int(view_cache_ttl)
            if view_cache_ttl
            else view_expiry * 9 // 10,
            concurrency=int(os.getenv("MEDIA_VIEW_CONCURRENCY", "10")),
            purge_after=int(os.getenv("MEDIA_PURGE_AFTER", str(7 * 24 * 3600))),
            page_size=int(os.getenv("MEDIA_PAGE_SIZE", "50")),
            max_page_size=int(os.getenv("MEDIA_MAX_PAGE_SIZE", "100")),
            delete_max_depth=int(os.getenv("MEDIA_DELETE_MAX_DEPTH", "3")),
        )
