"""Simple in-memory sliding-window rate limiter (per client IP)."""

import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional, Tuple

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import get_settings

_CREATE_ROUTES = (
    ("POST", "/api/transcript"),
    ("POST", "/api/transcript/upload"),
    ("POST", "/api/live"),
    ("POST", "/api/convert/txt-to-json"),
)


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, bucket: str, limit: int, window: float = 60.0) -> Optional[float]:
        """Record a hit. Returns seconds to wait if over the limit, else None."""
        if limit <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            q = self._hits[(key, bucket)]
            while q and q[0] <= now - window:
                q.popleft()
            if len(q) >= limit:
                return max(1.0, window - (now - q[0]))
            q.append(now)
            if len(self._hits) > 50_000:
                self._hits = defaultdict(deque, {k: v for k, v in self._hits.items() if v})
            return None


def client_ip(request: Request) -> str:
    if get_settings().trust_proxy_headers:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, limiter: Optional[SlidingWindowLimiter] = None) -> None:
        super().__init__(app)
        self.limiter = limiter or SlidingWindowLimiter()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or request.method == "OPTIONS" or path.endswith("/events") or path == "/api/health":
            return await call_next(request)
        settings = get_settings()
        ip = client_ip(request)
        wait = self.limiter.hit(ip, "all", settings.rate_limit_per_minute)
        if wait is None and (request.method, path.rstrip("/")) in _CREATE_ROUTES:
            wait = self.limiter.hit(ip, "create", settings.rate_limit_job_create_per_minute)
        if wait is not None:
            return JSONResponse(
                status_code=429,
                headers={"Retry-After": str(int(wait))},
                content={"error": {
                    "code": "rate_limited",
                    "message": f"Too many requests. Please wait {int(wait)} seconds and try again.",
                    "hint": None,
                }},
            )
        return await call_next(request)
