import json
import logging

from fastapi.testclient import TestClient

from app.infrastructure.config import Settings
from app.infrastructure.logging import JsonFormatter, request_id
from app.main import create_app


def make_app():
    return create_app(
        Settings(
            _env_file=None,  # pyright: ignore[reportCallIssue]
            database_url="postgresql+asyncpg://test:test@localhost/test",
            cors_origins=["http://localhost:5173"],
        )
    )


def test_request_logs_are_correlated_and_exclude_user_data(capsys):
    app = make_app()

    @app.get("/example/{value}")
    async def example(value: str):
        logging.getLogger("app.example").info("example.loaded")
        return {"ok": True}

    with TestClient(app) as client:
        response = client.get(
            "/example/private-value?token=secret-query",
            headers={
                "Authorization": "Bearer secret-auth",
                "X-Request-ID": "spoofed-id",
                "Origin": "http://localhost:5173",
            },
        )
        second = client.get("/unknown-private-value")
    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines()]
    requests = [event for event in events if event["message"] == "http.request"]
    first = requests[0]
    assert first["request_id"] == response.headers["x-request-id"]
    assert len(first["request_id"]) == 32
    assert first["route"] == "/example/{value}"
    assert first["status_code"] == 200
    assert first["duration_ms"] >= 0
    assert requests[1]["route"] == "<unmatched>"
    assert requests[1]["level"] == "WARNING"
    assert second.headers["x-request-id"] != first["request_id"]
    assert (
        next(e for e in events if e["message"] == "example.loaded")["request_id"]
        == (first["request_id"])
    )
    assert "X-Request-ID" in response.headers["access-control-expose-headers"]
    for secret in ("private-value", "secret-query", "secret-auth", "spoofed-id"):
        assert secret not in output
    assert events[-1]["request_id"] is None
    assert request_id.get() is None


def test_unhandled_errors_have_safe_stack_and_response_request_id(capsys):
    app = make_app()

    @app.get("/broken")
    async def broken():
        raise RuntimeError("password=secret-exception")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/broken")
    output = capsys.readouterr().out
    events = [json.loads(line) for line in output.splitlines()]
    event = next(e for e in events if e.get("exception_type") == "RuntimeError")
    assert response.status_code == 500
    assert event["request_id"] == response.headers["x-request-id"]
    assert event["status_code"] == 500
    assert event["level"] == "ERROR"
    assert any(frame["function"] == "broken" for frame in event["stack"])
    assert "secret-exception" not in output + response.text


def test_formatter_only_includes_allowed_extra_fields():
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "order.created", (), None)
    record.order_id = 42
    record.payment = "secret-payment"
    event = json.loads(JsonFormatter("production").format(record))
    assert event["order_id"] == 42
    assert event["environment"] == "production"
    assert "secret-payment" not in json.dumps(event)
