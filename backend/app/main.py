"""TrustLens API. Run from backend/:  uvicorn app.main:app --reload --port 8000   (Swagger at /docs)"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .db import get_db
from .routes import router
from .routes_research import router as research_router
from .schema import ensure_gov_schema


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_gov_schema(get_db())
    yield


app = FastAPI(
    title="TrustLens API",
    version="0.1.0-m0",
    description="Evidence-backed clinical AI with audited lineage. Routes marked with the response header "
                "`X-TrustLens-Stub: true` still return contract-shaped example data.",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000"], allow_methods=["*"], allow_headers=["*"],
                   expose_headers=["X-TrustLens-Stub"])
app.include_router(research_router)
app.include_router(router)


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    code = {400: "bad_request", 404: "not_found", 409: "conflict", 501: "not_implemented"}.get(exc.status_code, "error")
    return _error(exc.status_code, code, str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else {}
    where = ".".join(str(p) for p in first.get("loc", []))
    return _error(422, "invalid_request", f"{where}: {first.get('msg', 'invalid input')}")


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    return _error(500, "internal_error", f"{type(exc).__name__}: {exc}")
