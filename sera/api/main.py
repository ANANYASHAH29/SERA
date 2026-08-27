"""FastAPI app entrypoint.

Run with:  uvicorn sera.api.main:app --reload
Then open http://127.0.0.1:8000/docs for the Swagger UI, or run the
frontend (see frontend/README.md) against this same backend.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from sera.api.routes_badge import router as badge_router
from sera.api.routes_experiments import router as experiments_router
from sera.api.routes_incidents import router as incidents_router
from sera.api.routes_report import router as report_router
from sera.api.routes_runs import router as runs_router
from sera.api.routes_tenant import router as tenant_router
from sera.api.routes_validate import router as validate_router
from sera.api.routes_webhook import router as webhook_router
from sera.config import RESULTS_DIR

app = FastAPI(
    title="SERA",
    description=(
        "Determines whether an accuracy regression in a CV pipeline was "
        "caused by a specific commit or by genuine data distribution shift."
    ),
    version="0.1.0",
)

# CORS is wide open here because this is a local research prototype talking
# to a local Vite dev server on a different port -- not a public deployment.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(runs_router)
app.include_router(incidents_router)
app.include_router(validate_router)
app.include_router(experiments_router)
app.include_router(tenant_router)
app.include_router(webhook_router)
app.include_router(badge_router)
app.include_router(report_router)

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/results-static", StaticFiles(directory=str(RESULTS_DIR)), name="results-static")


@app.get("/health")
def health():
    return {"status": "ok"}
