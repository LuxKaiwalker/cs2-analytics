"""One error shape for the whole API.

Every failure response is ``{"error": {"code", "message", "details"?}}``. The frontend
branches on ``code``, so FastAPI's default validation body is overridden to match —
otherwise 422s would be the one response shape the client could not handle uniformly.

``message`` is written for a user. Filesystem paths, stack traces and parser internals
stay in the server log.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """An error with a machine-readable code and a safe user-facing message."""

    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def error_body(code: str, message: str, details: dict[str, Any] | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if details:
        payload["details"] = details
    return {"error": payload}


# --- Ready-made errors for the cases the API actually raises --------------------


def not_found(resource: str = "match") -> ApiError:
    return ApiError(
        code="not_found",
        message=f"No such {resource}.",
        status_code=status.HTTP_404_NOT_FOUND,
    )


def payload_too_large(limit_bytes: int, actual_bytes: int | None = None) -> ApiError:
    details: dict[str, Any] = {"limit_bytes": limit_bytes}
    if actual_bytes is not None:
        details["received_bytes"] = actual_bytes
    return ApiError(
        code="file_too_large",
        message=(
            f"The demo exceeds the {limit_bytes // (1024 * 1024)} MiB upload limit. "
            "Raise CS2A_MAX_DEMO_BYTES to allow larger files."
        ),
        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
        details=details,
    )


def unsupported_media_type(received: str | None) -> ApiError:
    return ApiError(
        code="unsupported_media_type",
        message=(
            "Upload the demo as a raw request body with Content-Type 'application/octet-stream'."
        ),
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        details={"received": received} if received else None,
    )


def duplicate_match(match_id: str) -> ApiError:
    return ApiError(
        code="duplicate_demo",
        message="This demo has already been uploaded.",
        status_code=status.HTTP_409_CONFLICT,
        details={"match_id": match_id},
    )


def insufficient_storage(message: str) -> ApiError:
    return ApiError(
        code="insufficient_storage",
        message=message,
        status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
    )


def queue_full(depth: int) -> ApiError:
    return ApiError(
        code="queue_full",
        message="The processing queue is full. Try again once a match finishes.",
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        details={"queue_depth": depth},
    )


def invalid_request(code: str, message: str, **details: Any) -> ApiError:
    return ApiError(
        code=code,
        message=message,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        details=details or None,
    )


def register_error_handlers(app: FastAPI) -> None:
    """Install handlers so every error path returns the same envelope."""

    @app.exception_handler(ApiError)
    def _api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.code, exc.message, exc.details),
        )

    @app.exception_handler(RequestValidationError)
    def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        # Reshaped into our envelope so the client has exactly one error format.
        fields = [
            {
                "field": ".".join(str(part) for part in err.get("loc", ()) if part != "body"),
                "message": err.get("msg", "invalid value"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=error_body(
                "validation_error", "Some request parameters were invalid.", {"fields": fields}
            ),
        )

    @app.exception_handler(ValidationError)
    def _model_validation_error(_request: Request, exc: ValidationError) -> JSONResponse:
        # A model validated outside the request-parsing path (for example a query model
        # with a custom field validator) raises this directly. Without a handler it
        # would surface as a 500 for what is plainly a bad request.
        fields = [
            {
                "field": ".".join(str(part) for part in err.get("loc", ())),
                "message": err.get("msg", "invalid value"),
            }
            for err in exc.errors()
        ]
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content=error_body(
                "validation_error", "Some request parameters were invalid.", {"fields": fields}
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    def _http_error(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed", 401: "unauthorized"}
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(
                codes.get(exc.status_code, "http_error"),
                str(exc.detail) if exc.detail else "Request failed.",
            ),
        )

    @app.exception_handler(Exception)
    def _unhandled(request: Request, _exc: Exception) -> JSONResponse:
        # Logged in full server-side; the client gets no internals.
        logger.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=error_body("internal_error", "An unexpected error occurred."),
        )
