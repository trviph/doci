"""S3-compatible object store client.

Wraps the official (sync) :mod:`boto3` S3 client behind an ``async`` API: blocking
calls are offloaded with :func:`asyncio.to_thread` so the event loop never blocks.
Designed to be constructed once and injected as a dependency.
"""

import asyncio
import json
from collections.abc import AsyncIterator, Callable, Mapping
from typing import Any, TypeVar

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from cachetools import TLRUCache
from opentelemetry import trace
from opentelemetry.trace import SpanKind

from doci.objstore.config import ObjStoreConfig
from doci.objstore.models import ObjectMetadata, PresignedPost
from doci.telemetry import Counter, current_report, traced, with_metrics, with_span

_T = TypeVar("_T")

#: Bytes transferred through download/stream, tagged with a `direction` attribute.
OBJSTORE_BYTES = Counter(
    "doci.objstore.bytes", unit="By", description="Bytes transferred"
)

_DEFAULT_TRACER = trace.get_tracer("doci.objstore")


def _presign_ttu(_key: Any, value: tuple[Any, float], now: float) -> float:
    """time-to-use for the presign cache: entry expires at ``now + ttl``.

    ``value`` is ``(result, ttl)``; the per-entry ttl is set strictly below the
    URL's real validity (``expires_in - presign_clock_skew``) so a reused URL
    always keeps the skew margin of life, covering host/store clock drift.
    """
    return now + value[1]


@traced
class ObjStore:
    """Async client for an S3-compatible bucket.

    Construct with an :class:`ObjStoreConfig` (or :meth:`from_env`) and inject it
    where object storage is needed. Methods take an optional ``bucket`` that
    overrides the configured default.
    """

    def __init__(self, config: ObjStoreConfig) -> None:
        self._config = config
        self._s3: BaseClient = boto3.client(
            "s3", **self._client_kwargs(config.endpoint_url)
        )
        pub = config.public_endpoint_url
        # A distinct public endpoint needs its own client so signed URLs carry
        # the externally reachable host; otherwise reuse the main client.
        self._presign_s3: BaseClient = (
            boto3.client("s3", **self._client_kwargs(pub))
            if pub and pub != config.endpoint_url
            else self._s3
        )
        # Battle-tested TTL+LRU cache; per-entry TTL via the ttu callback. None
        # disables caching. Values are (result, ttl) tuples (see _presign_ttu).
        self._presign_cache: TLRUCache[tuple[Any, ...], tuple[Any, float]] | None = (
            TLRUCache(maxsize=config.presign_cache_max, ttu=_presign_ttu)
            if config.presign_cache_max > 0
            else None
        )

    @classmethod
    def from_env(cls) -> "ObjStore":
        return cls(ObjStoreConfig.from_env())

    # region lifecycle
    async def ping(self) -> None:
        """Liveness probe; raises if the store is unreachable. Used by health checks."""
        await asyncio.to_thread(self._ping_sync)

    def _ping_sync(self) -> None:
        if self._config.bucket:
            self._s3.head_bucket(Bucket=self._config.bucket)
        else:
            self._s3.list_buckets()

    def close(self) -> None:
        """Close the underlying boto3 client(s). Call on application shutdown."""
        self._s3.close()
        if self._presign_s3 is not self._s3:
            self._presign_s3.close()

    def __enter__(self) -> "ObjStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # endregion

    # region internals
    def _client_kwargs(self, endpoint_url: str | None) -> dict[str, Any]:
        style = "path" if self._config.force_path_style else "auto"
        return dict(
            endpoint_url=endpoint_url,
            region_name=self._config.region,
            aws_access_key_id=self._config.access_key_id,
            aws_secret_access_key=self._config.secret_access_key,
            config=Config(signature_version="s3v4", s3={"addressing_style": style}),
        )

    def _bucket(self, bucket: str | None) -> str:
        b = bucket or self._config.bucket
        if not b:
            raise ValueError("no bucket given and config.bucket is unset")
        return b

    def _expiry(self, expires_in: int | None) -> int:
        return expires_in if expires_in is not None else self._config.presign_expiry

    def _annotate(self, bucket: str, key: str) -> None:
        span = trace.get_current_span()
        span.set_attribute("aws.s3.bucket", bucket)
        span.set_attribute("aws.s3.key", key)

    def _cached_presign(
        self, cache_key: tuple[Any, ...], expires_in: int, generate: Callable[[], _T]
    ) -> _T:
        """Return a cached presigned result, or generate + cache it."""
        ttl = expires_in - self._config.presign_clock_skew
        if self._presign_cache is None or ttl <= 0:
            return generate()
        try:
            return self._presign_cache[cache_key][0]
        except KeyError:
            value = generate()
            self._presign_cache[cache_key] = (value, ttl)
            return value

    # endregion

    # region presigning (no network I/O)
    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def presign_put(
        self,
        key: str,
        *,
        bucket: str | None = None,
        expires_in: int | None = None,
        content_type: str | None = None,
        extra_params: Mapping[str, Any] | None = None,
    ) -> str:
        """Presigned URL for an HTTP ``PUT`` upload of ``key``."""
        b = self._bucket(bucket)
        exp = self._expiry(expires_in)
        self._annotate(b, key)
        params: dict[str, Any] = {"Bucket": b, "Key": key}
        if content_type:
            params["ContentType"] = content_type
        if extra_params:
            params.update(extra_params)
        cache_key = (
            "put",
            b,
            key,
            exp,
            json.dumps(params, sort_keys=True, default=str),
        )
        return self._cached_presign(
            cache_key,
            exp,
            lambda: self._presign_s3.generate_presigned_url(
                "put_object", Params=params, ExpiresIn=exp
            ),
        )

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def presign_post(
        self,
        key: str,
        *,
        bucket: str | None = None,
        expires_in: int | None = None,
        fields: dict[str, Any] | None = None,
        conditions: list[Any] | None = None,
    ) -> PresignedPost:
        """Presigned POST policy for a browser/form multipart upload of ``key``."""
        b = self._bucket(bucket)
        exp = self._expiry(expires_in)
        self._annotate(b, key)
        cache_key = (
            "post",
            b,
            key,
            exp,
            json.dumps(
                {"fields": fields, "conditions": conditions},
                sort_keys=True,
                default=str,
            ),
        )

        def generate() -> PresignedPost:
            resp = self._presign_s3.generate_presigned_post(
                Bucket=b, Key=key, Fields=fields, Conditions=conditions, ExpiresIn=exp
            )
            return PresignedPost(url=resp["url"], fields=resp["fields"])

        return self._cached_presign(cache_key, exp, generate)

    @with_span(kind=SpanKind.INTERNAL)
    @with_metrics()
    async def presign_get(
        self,
        key: str,
        *,
        bucket: str | None = None,
        expires_in: int | None = None,
        download_as: str | None = None,
    ) -> str:
        """Presigned URL to view (or, with ``download_as``, download) ``key``."""
        b = self._bucket(bucket)
        exp = self._expiry(expires_in)
        self._annotate(b, key)
        params: dict[str, Any] = {"Bucket": b, "Key": key}
        if download_as:
            params["ResponseContentDisposition"] = (
                f'attachment; filename="{download_as}"'
            )
        cache_key = ("get", b, key, exp, download_as or "")
        return self._cached_presign(
            cache_key,
            exp,
            lambda: self._presign_s3.generate_presigned_url(
                "get_object", Params=params, ExpiresIn=exp
            ),
        )

    # endregion

    # region object I/O (offloaded to threads)
    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def download(self, key: str, *, bucket: str | None = None) -> bytes:
        """Download the full object body as bytes."""
        b = self._bucket(bucket)
        self._annotate(b, key)
        data = await asyncio.to_thread(self._download_sync, b, key)
        current_report().record(OBJSTORE_BYTES, len(data), direction="down")
        return data

    def _download_sync(self, bucket: str, key: str) -> bytes:
        resp = self._s3.get_object(Bucket=bucket, Key=key)
        body = resp["Body"]
        try:
            return body.read()
        finally:
            body.close()

    async def stream(
        self, key: str, *, bucket: str | None = None, chunk_size: int = 65536
    ) -> AsyncIterator[bytes]:
        """Stream the object body in chunks (e.g. for a StreamingResponse).

        Not decorated with ``@with_span``/``@with_metrics``: those detect coroutine
        functions, not async generators, and would mis-wrap this. The span is opened
        manually so it covers the whole stream rather than just setup.
        """
        b = self._bucket(bucket)
        tracer = getattr(self, "__otel_tracer__", None) or _DEFAULT_TRACER
        with tracer.start_as_current_span(
            "ObjStore.stream", kind=SpanKind.CLIENT
        ) as span:
            span.set_attribute("aws.s3.bucket", b)
            span.set_attribute("aws.s3.key", key)
            resp = await asyncio.to_thread(self._s3.get_object, Bucket=b, Key=key)
            body = resp["Body"]
            total = 0
            try:
                while chunk := await asyncio.to_thread(body.read, chunk_size):
                    total += len(chunk)
                    yield chunk
            finally:
                body.close()
                span.set_attribute("doci.objstore.bytes", total)

    @with_span(kind=SpanKind.CLIENT)
    @with_metrics()
    async def get_metadata(
        self, key: str, *, bucket: str | None = None
    ) -> ObjectMetadata:
        """Fetch object metadata via ``head_object``."""
        b = self._bucket(bucket)
        self._annotate(b, key)
        head = await asyncio.to_thread(self._s3.head_object, Bucket=b, Key=key)
        return ObjectMetadata(
            bucket=b,
            key=key,
            size=head.get("ContentLength", 0),
            content_type=head.get("ContentType"),
            etag=head.get("ETag"),
            last_modified=head.get("LastModified"),
            metadata=head.get("Metadata", {}),
        )

    # endregion
