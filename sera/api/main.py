"""FastAPI app entrypoint.

Run with:  uvicorn sera.api.main:app --reload
Then open http://127.0.0.1:8000/docs for the Swagger UI, or run the
frontend (see frontend/README.md) against this same backend.
"""
from __future__ import annotations

import logging
import traceback

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from sera.api.routes_badge import router as badge_router
from sera.api.routes_experiments import router as experiments_router
from sera.api.routes_generic_scan import router as generic_scan_router
from sera.api.routes_incidents import router as incidents_router
from sera.api.routes_recovery import router as recovery_router
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

# CORS is wide open (any origin). Fine for a research prototype / demo
# deployment where every write endpoint is already gated by a user_id,
# report_token, or webhook signature -- CORS isn't acting as the real
# access control here, those are. Tighten `allow_origins` to your actual
# frontend's origin before this is anything more than a demo.
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
app.include_router(generic_scan_router)
app.include_router(recovery_router)

RESULTS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/results-static", StaticFiles(directory=str(RESULTS_DIR)), name="results-static")


@app.get("/health")
def health():
    return {"status": "ok"}


_logger = logging.getLogger("sera")


# TEMPORARY debugging aid: an unhandled exception in the deployed
# environment isn't reproducing locally with identical code+data, and
# there's no other way to see the real traceback from here. Remove this
# once the underlying bug is found -- it's not safe to ship long-term
# (leaks internals to any caller that manages to 500 an endpoint).
@app.exception_handler(Exception)
async def _debug_exception_handler(request: Request, exc: Exception):
    _logger.exception("unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "traceback": traceback.format_exc()},
    )
