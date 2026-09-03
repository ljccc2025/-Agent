import re
import pytest
from fastapi.testclient import TestClient
from opspilot.main import app
from opspilot.config import settings

@pytest.fixture
def client() -> TestClient:
    return TestClient(app)

def test_healthz_endpoint(client: TestClient):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "OpsPilot AI"
    assert "version" in data
    assert "read_only_mode" in data
    assert data["read_only_mode"] == settings.READ_ONLY_MODE
    assert "X-Process-Time" in resp.headers
    assert re.match(r"^\d+\.\d{4}s$", resp.headers["X-Process-Time"])

def test_root_endpoint(client: TestClient):
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "OpsPilot" in data["message"]
    assert "X-Process-Time" in resp.headers
    assert re.match(r"^\d+\.\d{4}s$", resp.headers["X-Process-Time"])

def test_cors_headers(client: TestClient):
    resp = client.options(
        "/healthz",
        headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"
    assert resp.headers.get("access-control-allow-credentials") is None
