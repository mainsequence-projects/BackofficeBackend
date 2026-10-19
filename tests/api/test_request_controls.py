"""Cancelled browser requests must not reach a business handler or become a 500."""

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.app.main import request_controls


@pytest.mark.parametrize("chunks", [[], [b'{"profile":']])
def test_disconnect_while_receiving_body_is_handled_before_business_code(chunks):
    app = FastAPI()
    app.middleware("http")(request_controls)
    calls = []

    @app.post("/command")
    def command():
        calls.append(True)
        return {"ok": True}

    messages = iter(
        [
            *({"type": "http.request", "body": chunk, "more_body": True} for chunk in chunks),
            {"type": "http.disconnect"},
        ]
    )
    sent = []

    async def receive():
        return next(messages, {"type": "http.disconnect"})

    async def send(message):
        sent.append(message)

    asyncio.run(
        app(
            {
                "type": "http",
                "asgi": {"version": "3.0", "spec_version": "2.4"},
                "http_version": "1.1",
                "method": "POST",
                "scheme": "http",
                "path": "/command",
                "raw_path": b"/command",
                "query_string": b"",
                "root_path": "",
                "headers": [(b"content-length", b"100")],
                "client": ("127.0.0.1", 49000),
                "server": ("127.0.0.1", 28641),
            },
            receive,
            send,
        )
    )
    assert not calls
    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 499
    assert dict(start["headers"])[b"cache-control"] == b"no-store"
    with TestClient(app) as client:
        assert client.post("/command", json={}).status_code == 200
    assert calls == [True]


def test_request_limit_and_complete_body_still_work():
    app = FastAPI()
    app.middleware("http")(request_controls)

    @app.post("/command")
    def command(body: dict):
        return body

    with TestClient(app) as client:
        assert client.post("/command", json={"value": "received"}).json() == {"value": "received"}
        response = client.post("/command", content=b"x" * (1024 * 1024 + 1))
        assert response.status_code == 413
        assert response.json()["detail"] == "request_exceeds_one_mib"
