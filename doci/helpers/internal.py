"""Internal-only guard: forbid invoking a callable from within an HTTP request.

Some service methods bypass the validation that the public API enforces (e.g.
``MediaService.upload`` skips the MIME/size checks ``finalize`` applies) and must
only ever run from in-process workflow nodes, never via a client request. FastAPI
never references service methods directly — route handlers wrap them — so a
route-registration scan can't catch a handler that calls one in its body. We
guard at runtime instead: an ASGI middleware flags the HTTP-request scope, and
``@internal`` raises if a marked callable is reached while that flag is set.
"""

import functools
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any, TypeVar

#: True while the current task is serving an HTTP request (set by the middleware).
_in_http_request: ContextVar[bool] = ContextVar("doci_in_http_request", default=False)

F = TypeVar("F", bound=Callable[..., Awaitable[Any]])


class InternalAccessError(RuntimeError):
    """Raised when an ``@internal`` callable is invoked during an HTTP request.

    Mapped to HTTP 403 Forbidden by an exception handler in ``create_app``.
    """


def internal(fn: F) -> F:
    """Mark an async method as internal: forbid calling it inside an HTTP request."""

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        if _in_http_request.get():
            raise InternalAccessError(
                f"{fn.__qualname__} is internal-only and must not be called "
                "from an HTTP request"
            )
        return await fn(*args, **kwargs)

    wrapper.__doci_internal__ = True  # marker for introspection / tests
    return wrapper  # type: ignore[return-value]


class HttpRequestContextMiddleware:
    """Pure-ASGI middleware: flags HTTP scopes so ``@internal`` can reject them.

    Implemented as raw ASGI (not ``BaseHTTPMiddleware``) so the contextvar is set
    in the same task that runs the endpoint and propagates through every ``await``.
    """

    def __init__(self, app: Any) -> None:
        self._app = app

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        token = _in_http_request.set(True)
        try:
            await self._app(scope, receive, send)
        finally:
            _in_http_request.reset(token)
