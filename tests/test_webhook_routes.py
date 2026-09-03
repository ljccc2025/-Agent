import pytest
from fastapi.testclient import TestClient
from opspilot.main import create_app

@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c

def test_webhook_alertmanager_firing_alerts(client):
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "KubePodCrashLooping",
                    "pod": "cart-service-59f7",
                    "namespace": "ecommerce"
                },
                "annotations": {
                    "summary": "Pod cart-service is crashing frequently"
                }
            }
        ]
    }
    resp = client.post("/webhook/alertmanager", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["dispatched_count"] == 1
    assert len(data["task_ids"]) == 1
    assert data["tasks"][0]["target_name"] == "cart-service-59f7"
    assert data["tasks"][0]["target_type"] == "k8s_pod"

def test_webhook_alertmanager_empty_alerts(client):
    payload = {"status": "firing", "alerts": []}
    resp = client.post("/webhook/alertmanager", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["dispatched_count"] == 0
    assert len(data["task_ids"]) == 0
