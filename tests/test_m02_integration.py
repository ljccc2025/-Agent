import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from opspilot.main import create_app
from opspilot.normalizer import (
    get_default_deduplicator,
    get_default_throttler,
)


@pytest.fixture
def client():
    app = create_app()
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def reset_normalizer_singletons():
    """每个集成测试运行前后清理单例缓存，保证用例独立隔离。"""
    get_default_deduplicator().clear()
    get_default_throttler().reset()
    yield
    get_default_deduplicator().clear()
    get_default_throttler().reset()


def test_alertmanager_deduplication_lifecycle(client: TestClient):
    """验证 Alertmanager Webhook 的去重防抖生命周期：
    1. 首次告警正常派发 (dispatched=1, dedup=0)
    2. 短时间内相同告警被去重拦截 (dispatched=0, dedup=1)
    3. 不同 Pod 告警正常派发 (dispatched=1, dedup=0)
    """
    alert_pod1 = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "PodHighMemory",
                    "pod": "payment-service-88a1",
                    "namespace": "production",
                    "severity": "critical",
                },
                "annotations": {
                    "summary": "Pod payment-service-88a1 memory usage > 90%"
                },
            }
        ],
    }

    with patch("opspilot.api.routes_webhook.async_diagnostic_worker") as mock_worker:
        # 1. 首次推送
        resp1 = client.post("/webhook/alertmanager", json=alert_pod1)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["status"] == "ok"
        assert data1["dispatched_count"] == 1
        assert data1["deduplicated_count"] == 0
        assert data1["storm_throttled_count"] == 0
        assert len(data1["task_ids"]) == 1
        assert len(data1["tasks"]) == 1
        task1 = data1["tasks"][0]
        assert task1["target_name"] == "payment-service-88a1"
        assert task1["target_type"] == "k8s_pod"
        assert task1["namespace"] == "production"
        assert task1["duplicate_count"] == 0
        assert task1["fingerprint"] is not None
        mock_worker.assert_called_once_with(data1["task_ids"][0], "payment-service-88a1")

        # 2. 短时间内再次推送相同告警 -> 去重拦截
        mock_worker.reset_mock()
        resp2 = client.post("/webhook/alertmanager", json=alert_pod1)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "ok"
        assert data2["dispatched_count"] == 0
        assert data2["deduplicated_count"] == 1
        assert data2["storm_throttled_count"] == 0
        assert len(data2["task_ids"]) == 0
        assert len(data2["tasks"]) == 0
        mock_worker.assert_not_called()

        # 3. 推送不同 Pod 的告警 -> 正常派发
        mock_worker.reset_mock()
        alert_pod2 = {
            "status": "firing",
            "alerts": [
                {
                    "status": "firing",
                    "labels": {
                        "alertname": "PodHighMemory",
                        "pod": "order-service-33b2",
                        "namespace": "production",
                        "severity": "critical",
                    },
                    "annotations": {
                        "summary": "Pod order-service-33b2 memory usage > 90%"
                    },
                }
            ],
        }
        resp3 = client.post("/webhook/alertmanager", json=alert_pod2)
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["status"] == "ok"
        assert data3["dispatched_count"] == 1
        assert data3["deduplicated_count"] == 0
        assert len(data3["task_ids"]) == 1
        assert data3["tasks"][0]["target_name"] == "order-service-33b2"
        mock_worker.assert_called_once_with(data3["task_ids"][0], "order-service-33b2")


def test_grafana_webhook_lifecycle(client: TestClient):
    """验证 Grafana Webhook 全流程：
    1. 向 /webhook/grafana 推送告警正常派发
    2. 再次推送相同告警被去重拦截
    3. 推送 state="ok" 恢复通知被过滤无任务生成
    """
    grafana_alert = {
        "ruleName": "HighLatencyWarning",
        "state": "alerting",
        "title": "[Alerting] HighLatencyWarning",
        "message": "Service response latency is higher than 500ms",
        "commonLabels": {
            "environment": "prod",
            "namespace": "core",
        },
        "evalMatches": [
            {
                "metric": "auth-service-01",
                "value": 650.0,
                "tags": {
                    "pod": "auth-service-01",
                    "severity": "warning",
                },
            }
        ],
    }

    with patch("opspilot.api.routes_webhook.async_diagnostic_worker") as mock_worker:
        # 1. 首次推送 Grafana 告警
        resp1 = client.post("/webhook/grafana", json=grafana_alert)
        assert resp1.status_code == 200
        data1 = resp1.json()
        assert data1["status"] == "ok"
        assert data1["dispatched_count"] == 1
        assert data1["deduplicated_count"] == 0
        assert len(data1["task_ids"]) == 1
        assert data1["tasks"][0]["source"] == "grafana"
        assert data1["tasks"][0]["target_name"] == "auth-service-01"
        assert data1["tasks"][0]["target_type"] == "k8s_pod"
        assert data1["tasks"][0]["namespace"] == "core"
        mock_worker.assert_called_once_with(data1["task_ids"][0], "auth-service-01")

        # 2. 再次发送相同告警 -> 被去重拦截
        mock_worker.reset_mock()
        resp2 = client.post("/webhook/grafana", json=grafana_alert)
        assert resp2.status_code == 200
        data2 = resp2.json()
        assert data2["status"] == "ok"
        assert data2["dispatched_count"] == 0
        assert data2["deduplicated_count"] == 1
        assert len(data2["task_ids"]) == 0
        mock_worker.assert_not_called()

        # 3. 发送 state="ok" 恢复通知 -> 自动过滤
        mock_worker.reset_mock()
        grafana_ok = {
            "ruleName": "HighLatencyWarning",
            "state": "ok",
            "title": "[OK] HighLatencyWarning",
            "message": "Latency returned to normal",
            "evalMatches": [],
        }
        resp3 = client.post("/webhook/grafana", json=grafana_ok)
        assert resp3.status_code == 200
        data3 = resp3.json()
        assert data3["status"] == "ok"
        assert data3["dispatched_count"] == 0
        assert data3["deduplicated_count"] == 0
        assert len(data3["task_ids"]) == 0
        assert len(data3["tasks"]) == 0
        mock_worker.assert_not_called()


def test_alert_storm_burst_aggregation_via_webhook(client: TestClient):
    """模拟突发大量（60条）告警涌入 Webhook，验证自动触发风暴合并：
    - storm_throttled_count > 0
    - 代表性任务携带 is_storm_aggregated=True
    - 后台 worker 仅收到聚合后的代表性任务分发
    """
    # 构造 60 条针对同一故障域 (pod=gateway-ingress-01) 但告警名不同的告警，确保防抖不拦截但触发风暴
    alerts = []
    for i in range(60):
        alerts.append({
            "status": "firing",
            "labels": {
                "alertname": f"StormAlert_{i:03d}",
                "pod": "gateway-ingress-01",
                "namespace": "ingress-system",
                "cluster": "k8s-prod",
            },
            "annotations": {
                "summary": f"Storm alert number {i} triggered on gateway",
            },
        })

    payload = {
        "status": "firing",
        "alerts": alerts,
    }

    with patch("opspilot.api.routes_webhook.async_diagnostic_worker") as mock_worker:
        resp = client.post("/webhook/alertmanager", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        # 60 条告警超过风暴阈值 50，应被聚合成 1 个代表任务
        assert data["dispatched_count"] == 1
        assert data["storm_throttled_count"] == 59
        assert data["deduplicated_count"] == 0
        assert len(data["task_ids"]) == 1
        assert len(data["tasks"]) == 1

        primary_task = data["tasks"][0]
        assert primary_task["is_storm_aggregated"] is True
        assert "[告警风暴聚合 - 归并60条告警]" in primary_task["symptoms"]
        assert primary_task["target_name"] == "gateway-ingress-01"
        assert primary_task["target_type"] == "k8s_pod"
        assert primary_task["namespace"] == "ingress-system"
        assert "storm_associated_alerts" in primary_task["alert_labels"]
        assert len(primary_task["alert_labels"]["storm_associated_alerts"]) == 59

        # 异步后台仅分发了这 1 个代表性任务
        mock_worker.assert_called_once_with(primary_task["task_id"], "gateway-ingress-01")


def test_alertmanager_mixed_batch_dedup_and_resolved(client: TestClient):
    """验证包含历史重复告警、全新告警与已恢复告警的混合批次处理。"""
    alert_existing = {
        "status": "firing",
        "labels": {"alertname": "NodeDiskFilling", "instance": "192.168.1.50:9100"},
        "annotations": {"summary": "Disk 90% full"},
    }

    # 1. 预先推送一次使其进入去重窗口
    with patch("opspilot.api.routes_webhook.async_diagnostic_worker"):
        client.post("/webhook/alertmanager", json={"status": "firing", "alerts": [alert_existing]})

    # 2. 混合批次：1 条重复 + 1 条全新 + 1 条已恢复
    mixed_batch = {
        "status": "firing",
        "alerts": [
            alert_existing,  # 重复 -> 去重抑制
            {
                "status": "firing",  # 全新 -> 正常派发
                "labels": {"alertname": "PodCrashLoop", "pod": "cart-88", "namespace": "shop"},
                "annotations": {"summary": "CrashLoopBackOff"},
            },
            {
                "status": "resolved",  # 已恢复 -> 过滤忽略
                "labels": {"alertname": "CpuHigh", "instance": "192.168.1.60:9100"},
            },
        ],
    }

    with patch("opspilot.api.routes_webhook.async_diagnostic_worker") as mock_worker:
        resp = client.post("/webhook/alertmanager", json=mixed_batch)
        assert resp.status_code == 200
        data = resp.json()
        assert data["dispatched_count"] == 1
        assert data["deduplicated_count"] == 1
        assert data["storm_throttled_count"] == 0
        assert len(data["task_ids"]) == 1
        assert data["tasks"][0]["target_name"] == "cart-88"
        mock_worker.assert_called_once_with(data["task_ids"][0], "cart-88")


def test_openapi_spec_has_both_webhooks(client: TestClient):
    """验证 /openapi.json 中完整包含 /webhook/alertmanager 和 /webhook/grafana。"""
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    paths = spec.get("paths", {})
    assert "/webhook/alertmanager" in paths, "OpenAPI spec should contain /webhook/alertmanager"
    assert "post" in paths["/webhook/alertmanager"], "POST method should exist for /webhook/alertmanager"
    assert "/webhook/grafana" in paths, "OpenAPI spec should contain /webhook/grafana"
    assert "post" in paths["/webhook/grafana"], "POST method should exist for /webhook/grafana"
