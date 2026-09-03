from fastapi.testclient import TestClient
from opspilot.main import app

client = TestClient(app)

def test_healthz_endpoint():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert data["service"] == "OpsPilot AI"
    assert "version" in data
    assert "X-Process-Time" in resp.headers

def test_root_endpoint():
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert "OpsPilot" in data["message"]
