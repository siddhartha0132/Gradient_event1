"""One error shape for every API error: {"error": {"code", "message", "details"}}."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        self.status = status
        self.code = code
        self.message = message
        self.details = details or {}


def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found")


def forbidden(message: str = "You do not have access to this") -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def _body(code: str, message: str, details: dict) -> dict:
    return {"error": {"code": code, "message": message, "details": details}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_: Request, exc: ApiError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        details = {"fields": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in exc.errors()]}
        return JSONResponse(_body("INVALID_REQUEST", "The request is not valid", details), status_code=422)
