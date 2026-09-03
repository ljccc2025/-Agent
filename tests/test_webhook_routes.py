from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from opspilot.main import create_app

@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c

def test_webhook_alertmanager_firing_alerts(client: TestClient):
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
    with patch("opspilot.api.routes_webhook.async_diagnostic_worker") as mock_worker:
        resp = client.post("/webhook/alertmanager", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["dispatched_count"] == 1
        assert len(data["task_ids"]) == 1
        assert data["tasks"][0]["target_name"] == "cart-service-59f7"
        assert data["tasks"][0]["target_type"] == "k8s_pod"
        assert data["tasks"][0]["namespace"] == "ecommerce"

        # 验证后台异步任务真实分发与参数传递
        mock_worker.assert_called_once_with(data["task_ids"][0], "cart-service-59f7")

def test_webhook_alertmanager_empty_alerts(client: TestClient):
    payload = {"status": "firing", "alerts": []}
    with patch("opspilot.api.routes_webhook.async_diagnostic_worker") as mock_worker:
        resp = client.post("/webhook/alertmanager", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["dispatched_count"] == 0
        assert len(data["task_ids"]) == 0
        assert len(data["tasks"]) == 0
        mock_worker.assert_not_called()

def test_webhook_alertmanager_linux_node_alert(client: TestClient):
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "NodeMemoryHigh",
                    "instance": "192.168.1.100:9100"
                },
                "annotations": {
                    "summary": "Host memory usage exceeds 90%"
                }
            }
        ]
    }
    with patch("opspilot.api.routes_webhook.async_diagnostic_worker") as mock_worker:
        resp = client.post("/webhook/alertmanager", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["dispatched_count"] == 1
        assert len(data["task_ids"]) == 1
        assert data["tasks"][0]["target_name"] == "192.168.1.100"
        assert data["tasks"][0]["target_type"] == "linux_node"
        assert data["tasks"][0]["namespace"] is None
        mock_worker.assert_called_once_with(data["task_ids"][0], "192.168.1.100")

def test_webhook_alertmanager_resolved_alert_filtering(client: TestClient):
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "resolved",
                "labels": {
                    "alertname": "KubePodCrashLooping",
                    "pod": "cart-service-59f7",
                    "namespace": "ecommerce"
                }
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "NodeDiskFull",
                    "instance": "10.0.0.5:9100"
                }
            }
        ]
    }
    with patch("opspilot.api.routes_webhook.async_diagnostic_worker") as mock_worker:
        resp = client.post("/webhook/alertmanager", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        # 仅分发 firing 告警
        assert data["dispatched_count"] == 1
        assert len(data["task_ids"]) == 1
        assert data["tasks"][0]["target_name"] == "10.0.0.5"
        mock_worker.assert_called_once_with(data["task_ids"][0], "10.0.0.5")

def test_webhook_alertmanager_all_resolved_alerts(client: TestClient):
    payload = {
        "status": "resolved",
        "alerts": [
            {
                "status": "resolved",
                "labels": {"alertname": "HighCPU", "pod": "svc-a"}
            }
        ]
    }
    with patch("opspilot.api.routes_webhook.async_diagnostic_worker") as mock_worker:
        resp = client.post("/webhook/alertmanager", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["dispatched_count"] == 0
        assert len(data["task_ids"]) == 0
        mock_worker.assert_not_called()

def test_webhook_alertmanager_multiple_alerts_batch_dispatch(client: TestClient):
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "PodCrash1", "pod": "pod-1", "namespace": "default"}
            },
            {
                "status": "firing",
                "labels": {"alertname": "PodCrash2", "pod": "pod-2", "namespace": "default"}
            },
            {
                "status": "firing",
                "labels": {"alertname": "NodeDown", "instance": "192.168.1.50:9100"}
            }
        ]
    }
    with patch("opspilot.api.routes_webhook.async_diagnostic_worker") as mock_worker:
        resp = client.post("/webhook/alertmanager", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["dispatched_count"] == 3
        assert len(data["task_ids"]) == 3
        assert mock_worker.call_count == 3
        targets = [call.args[1] for call in mock_worker.call_args_list]
        assert targets == ["pod-1", "pod-2", "192.168.1.50"]

def test_webhook_alertmanager_invalid_payload_422(client: TestClient):
    # 非法类型（alerts 字段应为 list）
    resp = client.post("/webhook/alertmanager", json={"alerts": "not-a-list"})
    assert resp.status_code == 422

def test_webhook_alertmanager_method_not_allowed_405(client: TestClient):
    resp = client.get("/webhook/alertmanager")
    assert resp.status_code == 405

def test_async_diagnostic_worker_direct_execution():
    from opspilot.api.routes_webhook import async_diagnostic_worker
    # 测试直接执行 worker 函数无异常
    async_diagnostic_worker("alert-123456", "test-target")
