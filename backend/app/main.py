"""
Application entrypoint. Creates the FastAPI app, wires middleware, mounts
all domain routers, and centralizes error responses into the
`{ "error": { code, message, details } }` envelope decided during API design.
"""

import logging

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.routers import (
    accounts,
    auth,
    budgets,
    categories,
    flat_rate,
    physical_assets,
    planning,
    portfolio,
    savings_goals,
    transactions,
)
from app.services.csv_import import CsvImportError

logging.basicConfig(level=logging.DEBUG if settings.debug else logging.INFO)
logger = logging.getLogger(__name__)

# The interactive docs and the OpenAPI schema describe every endpoint to
# anyone who asks; keep them for development only.
_docs_url = None if settings.is_production else "/docs"
_redoc_url = None if settings.is_production else "/redoc"
_openapi_url = None if settings.is_production else "/openapi.json"

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    docs_url=_docs_url,
    redoc_url=_redoc_url,
    openapi_url=_openapi_url,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Centralized error handling — every error response follows the same shape,
# regardless of whether it came from validation, an HTTPException, or an
# unhandled exception.
# ---------------------------------------------------------------------------

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        {"field": ".".join(str(p) for p in err["loc"]), "message": err["msg"]}
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": {
                "code": "VALIDATION_ERROR",
                "message": "One or more fields are invalid",
                "details": details,
            }
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": _code_for_status(exc.status_code),
                "message": exc.detail,
                "details": [],
            }
        },
        headers=exc.headers,
    )


@app.exception_handler(CsvImportError)
async def csv_import_error_handler(request: Request, exc: CsvImportError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"error": {"code": "CSV_IMPORT_ERROR", "message": str(exc), "details": []}},
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    # Never leak internals (stack traces, DB errors) to the client — log
    # them server-side instead, return a generic message.
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Something went wrong. Please try again.",
                "details": [],
            }
        },
    )


def _code_for_status(status_code: int) -> str:
    return {
        status.HTTP_401_UNAUTHORIZED: "UNAUTHORIZED",
        status.HTTP_403_FORBIDDEN: "FORBIDDEN",
        status.HTTP_404_NOT_FOUND: "NOT_FOUND",
        status.HTTP_409_CONFLICT: "CONFLICT",
        status.HTTP_422_UNPROCESSABLE_ENTITY: "UNPROCESSABLE_ENTITY",
        status.HTTP_429_TOO_MANY_REQUESTS: "RATE_LIMITED",
    }.get(status_code, "ERROR")


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(categories.router)
app.include_router(transactions.router)
app.include_router(budgets.router)
app.include_router(planning.router)
app.include_router(savings_goals.router)
app.include_router(portfolio.router)
app.include_router(physical_assets.router)
app.include_router(flat_rate.router)


@app.get("/health", tags=["health"])
def health_check() -> dict[str, str]:
    """Used by Docker healthcheck / uptime monitoring."""
    return {"status": "ok"}