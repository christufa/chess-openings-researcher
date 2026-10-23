"""Read-only research explorer. Run with uvicorn openings_research.api:app."""

import os
import threading
import time
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .serving import IcebergReader, ResearchReader, StoreUnavailable
from .tree import START, BookTree

PageSize = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]
RunID = Annotated[str, Query(min_length=1, max_length=200)]


class RateLimiter:
    """Token bucket per client: `burst` requests at once, refilled at `per_second`.

    Per replica and in memory, like lichess-delta-kube's public API. Buckets idle long
    enough to be full again are dropped, so memory stays bounded by active clients.
    """

    def __init__(self, per_second: float, burst: int, timer=time.monotonic):
        self.per_second, self.burst, self._timer = per_second, burst, timer
        self._idle = burst / per_second if per_second > 0 else 60.0
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.per_second > 0 and self.burst > 0

    def take(self, key: str) -> float:
        """Takes one token: 0 if allowed, else the seconds until one is free."""
        now = self._timer()
        with self._lock:
            if len(self._buckets) > 10_000:
                self._buckets = {k: v for k, v in self._buckets.items() if now - v[1] < self._idle}
            tokens, last = self._buckets.get(key, (float(self.burst), now))
            tokens = min(float(self.burst), tokens + (now - last) * self.per_second)
            if tokens >= 1:
                self._buckets[key] = (tokens - 1, now)
                return 0.0
            self._buckets[key] = (tokens, now)
            return (1 - tokens) / self.per_second


def client_ip(request: Request) -> str:
    # Public traffic arrives only through the Cloudflare Tunnel (network policy admits only
    # cloudflared), and Cloudflare sets CF-Connecting-IP to the visitor's address.
    return request.headers.get("cf-connecting-ip") or (request.client.host if request.client else "unknown")


def create_app(reader=None, limiter=None):
    app = FastAPI(
        title="Openings Research", version="0.4.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    if reader is None:
        namespace = os.getenv("OPENINGS_READ_NAMESPACE", "research.openings_research")
        reader = ResearchReader(IcebergReader(namespace), namespace)

    limiter = limiter or RateLimiter(
        float(os.getenv("OPENINGS_RATE_LIMIT_PER_SECOND", "5")), int(os.getenv("OPENINGS_RATE_LIMIT_BURST", "60"))
    )

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        # Only the API is limited; the explorer's static files are cheap.
        if request.url.path.startswith("/api/") and limiter.enabled:
            wait = limiter.take(client_ip(request))
            if wait:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests"},
                    headers={"Retry-After": str(max(1, round(wait)))},
                )
        return await call_next(request)

    @app.exception_handler(StoreUnavailable)
    async def unavailable(request: Request, exc: StoreUnavailable):
        return JSONResponse(status_code=503, content={"detail": "Research store unavailable"})

    @app.exception_handler(LookupError)
    async def missing(request: Request, exc: LookupError):
        return JSONResponse(status_code=404, content={"detail": "Completed run not found"})

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": "Invalid comparison or research data"})

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready():
        # Catalog reachable and the research namespace readable; table reads are per request.
        reader.db.ping() if hasattr(reader.db, "ping") else reader.db.query("SELECT 1 AS ok")
        return {"status": "ok"}

    @app.get("/api/v1/openings")
    def openings(limit: PageSize = 50, offset: Offset = 0):
        return {"items": reader.openings(limit, offset), "limit": limit, "offset": offset}

    @app.get("/api/v1/openings/{opening_id}/runs")
    def runs(opening_id: str, limit: PageSize = 50):
        return {"items": reader.runs(opening_id, limit)}

    @app.get("/api/v1/runs/{run_id}/claims")
    def claims(run_id: str, limit: PageSize = 100, offset: Offset = 0):
        return {"items": reader.records(run_id, "claims", limit, offset), "limit": limit, "offset": offset}

    @app.get("/api/v1/runs/{run_id}/lines")
    def lines(run_id: str, limit: PageSize = 100, offset: Offset = 0):
        return {"items": reader.records(run_id, "lines", limit, offset), "limit": limit, "offset": offset}

    @app.get("/api/v1/runs/{run_id}/evidence/{candidate_id}")
    def evidence(run_id: str, candidate_id: str, limit: PageSize = 100, offset: Offset = 0):
        return {"items": reader.evidence(run_id, candidate_id, limit, offset)}

    @app.get("/api/v1/runs/{run_id}/coverage")
    def coverage(run_id: str):
        return {"report": reader.coverage(run_id)}

    books = {}  # one tree per published-lines snapshot; rebuilt only when lines change

    @app.get("/api/v1/tree")
    def tree(fen: Annotated[str, Query(min_length=10, max_length=100)] = START["normalized_fen"]):
        """Book moves from a position: every researched line through it, merged across openings."""
        lines = reader.book_lines()
        key = hash(tuple((r["opening"], r["name"], r["start_fen"], tuple(r["moves_uci"])) for r in lines))
        if key not in books:
            books.clear()
            books[key] = BookTree(lines)
        return books[key].lookup(fen)

    @app.get("/api/v1/compare")
    def compare(before: RunID, after: RunID):
        return reader.compare(before, after)

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="explorer")
    return app


app = create_app()
