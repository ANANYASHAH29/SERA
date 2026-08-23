"""FastAPI app entrypoint.

Run with:  uvicorn sera.api.main:app --reload
Then open http://127.0.0.1:8000/docs for the Swagger UI.
"""
from __future__ import annotations

from fastapi import FastAPI

from sera.api.routes_incidents import router as incidents_router
from sera.api.routes_runs import router as runs_router
from sera.api.routes_validate import router as validate_router

app = FastAPI(
    title="SERA",
    description=(
        "Determines whether an accuracy regression in a CV pipeline was "
        "caused by a specific commit or by genuine data distribution shift."
    ),
    version="0.1.0",
)

app.include_router(runs_router)
app.include_router(incidents_router)
app.include_router(validate_router)


@app.get("/health")
def health():
    return {"status": "ok"}
