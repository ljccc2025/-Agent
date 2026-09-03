import re
import pytest
from fastapi.testclient import TestClient
from opspilot.main import create_app
from opspilot.config import settings

@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c

def test_m01_full_lifecycle(client: TestClient):
    # 1. 验证系统健康状态与响应头
    health_resp = client.get("/healthz")
    assert health_resp.status_code == 200
    health_data = health_resp.json()
    assert health_data["status"] == "healthy"
    assert health_data["service"] == settings.APP_NAME
    assert health_data["read_only_mode"] is True
    assert "X-Process-Time" in health_resp.headers
    assert re.match(r"^\d+\.\d{4}s$", health_resp.headers["X-Process-Time"])

    # 2. 模拟 Alertmanager 复杂批量告警 Webhook (Pod + Node + Resolved)
    alert_payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "PodOOMKilled", "pod": "gateway-0", "namespace": "default"},
                "annotations": {"summary": "Pod terminated with exit code 137"}
            },
            {
                "status": "firing",
                "labels": {"alertname": "HostDiskPressure", "instance": "10.0.1.20:9100"},
                "annotations": {"description": "Disk usage > 95% on /dev/vda1"}
            },
            {
                "status": "resolved",
                "labels": {"alertname": "PodCrashLooping", "pod": "auth-service", "namespace": "default"},
                "annotations": {"summary": "Alert resolved"}
            }
        ]
    }
    wh_resp = client.post("/webhook/alertmanager", json=alert_payload)
    assert wh_resp.status_code == 200
    wh_data = wh_resp.json()
    assert wh_data["status"] == "ok"
    assert wh_data["dispatched_count"] == 2  # resolved 自动过滤
    assert len(wh_data["task_ids"]) == 2
    assert wh_data["tasks"][0]["target_name"] == "gateway-0"
    assert wh_data["tasks"][0]["target_type"] == "k8s_pod"
    assert wh_data["tasks"][1]["target_name"] == "10.0.1.20"  # 端口已清洗
    assert wh_data["tasks"][1]["target_type"] == "linux_node"

    # 3. 模拟 SRE 手动发起针对主机的排障请求
    diag_req = {
        "target_type": "linux_node",
        "target_name": "10.0.1.20",
        "symptoms": "Disk usage > 98%"
    }
    diag_resp = client.post("/api/v1/diagnose", json=diag_req)
    assert diag_resp.status_code == 200
    diag_data = diag_resp.json()
    assert diag_data["status"] == "dispatched"
    assert diag_data["task"]["target_name"] == "10.0.1.20"
    assert diag_data["task"]["target_type"] == "linux_node"
    assert diag_data["task"]["namespace"] is None

    # 4. 验证 OpenAPI 接口契约正常暴露
    openapi_resp = client.get("/openapi.json")
    assert openapi_resp.status_code == 200
    paths = openapi_resp.json()["paths"]
    assert "/healthz" in paths
    assert "/webhook/alertmanager" in paths
    assert "/api/v1/diagnose" in paths
