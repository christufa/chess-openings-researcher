"""Read-only research explorer. Run with uvicorn openings_research.api:app."""

import os
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .serving import IcebergReader, ResearchReader, StoreUnavailable

PageSize = Annotated[int, Query(ge=1, le=100)]
Offset = Annotated[int, Query(ge=0, le=10000)]
RunID = Annotated[str, Query(min_length=1, max_length=200)]


def create_app(reader=None):
    app = FastAPI(
        title="Openings Research", version="0.4.0", docs_url="/api/docs", openapi_url="/api/openapi.json"
    )
    if reader is None:
        namespace = os.getenv("OPENINGS_READ_NAMESPACE", "research.openings_research")
        reader = ResearchReader(IcebergReader(namespace), namespace)

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

    @app.get("/api/v1/compare")
    def compare(before: RunID, after: RunID):
        return reader.compare(before, after)

    app.mount("/", StaticFiles(directory=Path(__file__).parent / "web", html=True), name="explorer")
    return app


app = create_app()
