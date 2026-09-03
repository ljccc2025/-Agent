from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from opspilot.main import create_app

@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c

def test_manual_diagnose_k8s_pod_success(client: TestClient):
    """测试 K8s Pod 手动排障（显式命名空间，验证 200 响应与 mock worker 调用）"""
    req_payload = {
        "target_type": "k8s_pod",
        "target_name": "payment-api-prod-98b7",
        "namespace": "finance",
        "symptoms": "Payment gateway latency surge and HTTP 504 timeouts"
    }
    with patch("opspilot.api.routes_diagnose.async_manual_diagnostic_worker") as mock_worker:
        resp = client.post("/api/v1/diagnose", json=req_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "dispatched"
        assert data["task_id"].startswith("manual-")
        assert "dispatched successfully" in data["message"]
        assert data["task"]["task_id"] == data["task_id"]
        assert data["task"]["source"] == "manual_api"
        assert data["task"]["target_type"] == "k8s_pod"
        assert data["task"]["target_name"] == "payment-api-prod-98b7"
        assert data["task"]["namespace"] == "finance"
        assert data["task"]["symptoms"] == "Payment gateway latency surge and HTTP 504 timeouts"

        # 验证后台异步任务被正确调度并传参
        mock_worker.assert_called_once_with(data["task_id"], "payment-api-prod-98b7")

def test_manual_diagnose_linux_node_success(client: TestClient):
    """测试 Linux Node 手动排障（namespace 为 None，验证 200 响应与 mock worker 调用）"""
    req_payload = {
        "target_type": "linux_node",
        "target_name": "192.168.10.20",
        "namespace": None,
        "symptoms": "System load average exceeds 40 on 16-core host"
    }
    with patch("opspilot.api.routes_diagnose.async_manual_diagnostic_worker") as mock_worker:
        resp = client.post("/api/v1/diagnose", json=req_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "dispatched"
        assert data["task_id"].startswith("manual-")
        assert data["task"]["task_id"] == data["task_id"]
        assert data["task"]["source"] == "manual_api"
        assert data["task"]["target_type"] == "linux_node"
        assert data["task"]["target_name"] == "192.168.10.20"
        assert data["task"]["namespace"] is None
        assert data["task"]["symptoms"] == "System load average exceeds 40 on 16-core host"

        # 验证后台异步任务被正确调度
        mock_worker.assert_called_once_with(data["task_id"], "192.168.10.20")

def test_manual_diagnose_linux_node_omit_namespace(client: TestClient):
    """测试 Linux Node 省略 namespace 时自动规范化为 None"""
    req_payload = {
        "target_type": "linux_node",
        "target_name": "node-worker-03",
        "symptoms": "Disk /var/log usage reached 98%"
    }
    with patch("opspilot.api.routes_diagnose.async_manual_diagnostic_worker") as mock_worker:
        resp = client.post("/api/v1/diagnose", json=req_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["task"]["target_type"] == "linux_node"
        assert data["task"]["namespace"] is None
        mock_worker.assert_called_once_with(data["task_id"], "node-worker-03")

def test_manual_diagnose_k8s_pod_default_namespace(client: TestClient):
    """测试 K8s Pod 在未提供 namespace 时默认使用 'default'"""
    req_payload = {
        "target_type": "k8s_pod",
        "target_name": "ingress-controller-abc",
        "symptoms": "TLS handshake error rate > 5%"
    }
    with patch("opspilot.api.routes_diagnose.async_manual_diagnostic_worker") as mock_worker:
        resp = client.post("/api/v1/diagnose", json=req_payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["task"]["namespace"] == "default"
        mock_worker.assert_called_once_with(data["task_id"], "ingress-controller-abc")

def test_manual_diagnose_validation_errors_422(client: TestClient):
    """测试参数校验：缺失字段、空字符串、非法目标类型均返回 422"""
    # 1. 缺失 target_name
    resp1 = client.post("/api/v1/diagnose", json={
        "target_type": "k8s_pod",
        "symptoms": "Pod CrashLoopBackOff"
    })
    assert resp1.status_code == 422

    # 2. target_name 为空字符串 (min_length=1)
    resp2 = client.post("/api/v1/diagnose", json={
        "target_type": "k8s_pod",
        "target_name": "",
        "symptoms": "Pod CrashLoopBackOff"
    })
    assert resp2.status_code == 422

    # 3. 缺失 symptoms
    resp3 = client.post("/api/v1/diagnose", json={
        "target_type": "k8s_pod",
        "target_name": "order-api"
    })
    assert resp3.status_code == 422

    # 4. symptoms 为空字符串 (min_length=1)
    resp4 = client.post("/api/v1/diagnose", json={
        "target_type": "k8s_pod",
        "target_name": "order-api",
        "symptoms": ""
    })
    assert resp4.status_code == 422

    # 5. 非法 target_type（非 k8s_pod 或 linux_node）
    resp5 = client.post("/api/v1/diagnose", json={
        "target_type": "serverless_lambda",
        "target_name": "my-lambda",
        "symptoms": "Execution timeout"
    })
    assert resp5.status_code == 422

def test_manual_diagnose_method_not_allowed_405(client: TestClient):
    """测试不支持的 HTTP 请求方法返回 405"""
    resp = client.get("/api/v1/diagnose")
    assert resp.status_code == 405

def test_async_manual_diagnostic_worker_direct_execution():
    """测试后台诊断 worker 函数直接执行无异常"""
    from opspilot.api.routes_diagnose import async_manual_diagnostic_worker
    async_manual_diagnostic_worker("manual-abc12345", "test-workload")
