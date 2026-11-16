from __future__ import annotations

import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

log = logging.getLogger("myphoto.errors")


class AppError(Exception):
    def __init__(self, code: str, http_status: int, message: str):
        super().__init__(message)
        self.code = code
        self.http_status = http_status
        self.message = message


def _payload(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_request: Request, exc: AppError):
        return JSONResponse(_payload(exc.code, exc.message), status_code=exc.http_status)

    @app.exception_handler(Exception)
    async def handle_unexpected(_request: Request, exc: Exception):
        log.exception("unexpected error: %s", exc)
        return JSONResponse(_payload("internal_error", "internal server error"), status_code=500)
