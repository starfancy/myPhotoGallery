import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from myphoto.errors import AppError, install_error_handlers


def test_app_error_response_shape():
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise AppError(code="something_bad", http_status=418, message="teapot")

    r = TestClient(app).get("/boom")
    assert r.status_code == 418
    assert r.json() == {"error": {"code": "something_bad", "message": "teapot"}}


def test_uncaught_maps_to_internal_error(caplog):
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/boom")
    def boom():
        raise ValueError("unexpected")

    r = TestClient(app, raise_server_exceptions=False).get("/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["error"]["code"] == "internal_error"
