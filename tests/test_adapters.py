import re
import pytest
from opspilot.schemas.task import DiagnosticTask
from opspilot.normalizer.adapters import (
    BaseAlertAdapter,
    AlertmanagerAdapter,
    GrafanaAlertAdapter,
    GenericAlertAdapter,
    NormalizerRegistry,
    get_default_normalizer,
)


def test_alertmanager_adapter_pod_and_node():
    """Alertmanager 格式测试（Pod 提取、Node 端口清洗、fingerprint 自动注入）。"""
    adapter = AlertmanagerAdapter()
    payload = {
        "status": "firing",
        "receiver": "webhook",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "PodCrashLooping",
                    "pod": "order-api-7b8f9",
                    "namespace": "production",
                    "severity": "critical",
                },
                "annotations": {
                    "description": "Pod is crashing frequently"
                },
            },
            {
                "status": "firing",
                "labels": {
                    "alertname": "NodeDiskPressure",
                    "instance": "192.168.100.136:9100",
                    "severity": "warning",
                },
                "annotations": {
                    "summary": "Disk space low on node"
                },
            },
        ],
    }
    assert adapter.can_handle(payload) is True
    tasks = adapter.normalize(payload)
    assert len(tasks) == 2

    # Pod 任务验证
    pod_task = tasks[0]
    assert pod_task.target_type == "k8s_pod"
    assert pod_task.target_name == "order-api-7b8f9"
    assert pod_task.namespace == "production"
    assert pod_task.alert_name == "PodCrashLooping"
    assert pod_task.source == "alertmanager"
    assert pod_task.fingerprint is not None
    assert len(pod_task.fingerprint) == 16
    assert pod_task.symptoms == "Pod is crashing frequently"

    # Node 任务验证 (端口清洗)
    node_task = tasks[1]
    assert node_task.target_type == "linux_node"
    assert node_task.target_name == "192.168.100.136"
    assert node_task.namespace is None
    assert node_task.alert_name == "NodeDiskPressure"
    assert node_task.source == "alertmanager"
    assert node_task.fingerprint is not None
    assert len(node_task.fingerprint) == 16
    assert node_task.symptoms == "Disk space low on node"


def test_alertmanager_adapter_resolved_filtering():
    """Alertmanager 已恢复告警过滤。"""
    adapter = AlertmanagerAdapter()
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "CpuHigh", "pod": "user-service"},
                "annotations": {"description": "CPU high"},
            },
            {
                "status": "resolved",
                "labels": {"alertname": "MemHigh", "pod": "cart-service"},
                "annotations": {"description": "Mem high"},
            },
        ],
    }
    # firing_only=True 自动跳过已恢复项
    tasks = adapter.normalize(payload, firing_only=True)
    assert len(tasks) == 1
    assert tasks[0].target_name == "user-service"

    # firing_only=False 保留已恢复项
    all_tasks = adapter.normalize(payload, firing_only=False)
    assert len(all_tasks) == 2


def test_grafana_adapter_alerting_state():
    """Grafana Alerting 格式测试（state="alerting", ruleName, commonLabels）。"""
    adapter = GrafanaAlertAdapter()
    payload = {
        "title": "[Alerting] High Memory Usage",
        "ruleId": 42,
        "ruleName": "High Memory Usage",
        "state": "alerting",
        "message": "Memory usage exceeded 90% threshold",
        "commonLabels": {
            "alertname": "High Memory Usage",
            "instance": "192.168.100.136:9100",
            "severity": "critical",
        },
    }
    assert adapter.can_handle(payload) is True
    tasks = adapter.normalize(payload)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.source == "grafana"
    assert task.target_type == "linux_node"
    assert task.target_name == "192.168.100.136"
    assert task.alert_name == "High Memory Usage"
    assert task.symptoms == "Memory usage exceeded 90% threshold"
    assert task.fingerprint is not None
    assert len(task.fingerprint) == 16


def test_grafana_adapter_eval_matches():
    """Grafana evalMatches 结构解析。"""
    adapter = GrafanaAlertAdapter()
    payload = {
        "ruleName": "ServiceRestartsAlert",
        "state": "alerting",
        "message": "Services restarted unexpectedly",
        "commonLabels": {"cluster": "k8s-prod"},
        "evalMatches": [
            {
                "metric": "container_restarts",
                "tags": {
                    "pod": "auth-service-v1",
                    "namespace": "auth-zone",
                },
                "value": 5,
            },
            {
                "metric": "container_restarts",
                "tags": {
                    "pod": "payment-service-v2",
                    "namespace": "pay-zone",
                },
                "value": 12,
            },
        ],
    }
    assert adapter.can_handle(payload) is True
    tasks = adapter.normalize(payload)
    assert len(tasks) == 2

    assert tasks[0].source == "grafana"
    assert tasks[0].target_type == "k8s_pod"
    assert tasks[0].target_name == "auth-service-v1"
    assert tasks[0].namespace == "auth-zone"
    assert tasks[0].alert_labels.get("cluster") == "k8s-prod"
    assert tasks[0].alert_labels.get("pod") == "auth-service-v1"
    assert tasks[0].fingerprint is not None

    assert tasks[1].source == "grafana"
    assert tasks[1].target_type == "k8s_pod"
    assert tasks[1].target_name == "payment-service-v2"
    assert tasks[1].namespace == "pay-zone"
    assert tasks[1].alert_labels.get("cluster") == "k8s-prod"
    assert tasks[1].alert_labels.get("pod") == "payment-service-v2"
    assert tasks[1].fingerprint is not None


def test_grafana_adapter_ok_state_filtered():
    """Grafana state="ok" 自动过滤。"""
    adapter = GrafanaAlertAdapter()
    payload = {
        "ruleName": "High Memory Usage",
        "state": "ok",
        "commonLabels": {
            "instance": "192.168.100.136:9100",
        },
    }
    assert adapter.can_handle(payload) is True
    # firing_only=True 自动过滤 ok 状态
    tasks = adapter.normalize(payload, firing_only=True)
    assert len(tasks) == 0

    # firing_only=False 不做过滤
    all_tasks = adapter.normalize(payload, firing_only=False)
    assert len(all_tasks) == 1
    assert all_tasks[0].target_name == "192.168.100.136"


def test_generic_adapter_fallback():
    """任意扁平字典自动兜底。"""
    adapter = GenericAlertAdapter()
    payload = {
        "alert_name": "CustomDiskFull",
        "host": "storage-server-01:9100",
        "symptoms": "Disk usage > 98%",
        "custom_tag": "datacenter-a",
    }
    assert adapter.can_handle(payload) is True
    tasks = adapter.normalize(payload)
    assert len(tasks) == 1
    task = tasks[0]
    assert task.source == "generic"
    assert task.target_type == "linux_node"
    assert task.target_name == "storage-server-01"
    assert task.alert_name == "CustomDiskFull"
    assert task.symptoms == "Disk usage > 98%"
    assert task.fingerprint is not None
    assert len(task.fingerprint) == 16


def test_normalizer_registry_auto_dispatch():
    """Registry 自动根据 payload 结构选择正确的 Adapter。"""
    registry = get_default_normalizer()

    # Alertmanager 分发测试
    am_payload = {
        "status": "firing",
        "alerts": [
            {"labels": {"alertname": "AlertmanagerAlert", "pod": "nginx-pod"}},
        ],
    }
    am_tasks = registry.normalize(am_payload)
    assert len(am_tasks) == 1
    assert am_tasks[0].source == "alertmanager"
    assert am_tasks[0].target_name == "nginx-pod"

    # Grafana 分发测试
    gf_payload = {
        "ruleName": "GrafanaRule",
        "state": "alerting",
        "commonLabels": {"node": "worker-1"},
    }
    gf_tasks = registry.normalize(gf_payload)
    assert len(gf_tasks) == 1
    assert gf_tasks[0].source == "grafana"
    assert gf_tasks[0].target_name == "worker-1"

    # Generic 兜底分发测试
    gen_payload = {
        "alert_name": "GenericAlertEvent",
        "target_type": "linux_node",
        "target_name": "db-master",
        "symptoms": "IO wait high",
    }
    gen_tasks = registry.normalize(gen_payload)
    assert len(gen_tasks) == 1
    assert gen_tasks[0].source == "generic"
    assert gen_tasks[0].target_name == "db-master"


def test_fingerprint_auto_calculated_in_all_adapters():
    """断言所有解析出来的任务其 fingerprint 均非空且为 16 位小写十六进制。"""
    hex_16_pattern = re.compile(r"^[0-9a-f]{16}$")

    am_payload = {
        "status": "firing",
        "alerts": [
            {
                "labels": {
                    "alertname": "PodCrash",
                    "pod": "pod-1",
                    "namespace": "default",
                }
            }
        ],
    }
    gf_payload = {
        "ruleName": "NodeDown",
        "state": "alerting",
        "commonLabels": {"instance": "10.0.0.1"},
    }
    gen_payload = {
        "alert_name": "AppSlow",
        "pod": "api-gateway",
        "namespace": "gateway",
    }

    registry = get_default_normalizer()
    for p in [am_payload, gf_payload, gen_payload]:
        tasks = registry.normalize(p)
        assert len(tasks) == 1
        fp = tasks[0].fingerprint
        assert fp is not None
        assert len(fp) == 16
        assert hex_16_pattern.match(fp) is not None


def test_grafana_unified_alerting_alerts_list():
    """测试 Grafana Unified Alerting 格式（alerts 数组包含 firing 与 resolved）。"""
    adapter = GrafanaAlertAdapter()
    payload = {
        "ruleName": "UnifiedK8sAlert",
        "state": "alerting",
        "commonLabels": {"cluster": "production"},
        "alerts": [
            {
                "status": "firing",
                "labels": {"pod": "payment-api", "namespace": "finance"},
                "annotations": {"description": "Memory limit reached"},
            },
            {
                "status": "resolved",
                "labels": {"pod": "auth-api", "namespace": "auth"},
                "annotations": {"description": "Resolved"},
            },
        ],
    }
    assert adapter.can_handle(payload) is True
    # firing_only=True
    tasks = adapter.normalize(payload, firing_only=True)
    assert len(tasks) == 1
    assert tasks[0].target_name == "payment-api"
    assert tasks[0].namespace == "finance"
    assert tasks[0].source == "grafana"

    # firing_only=False
    all_tasks = adapter.normalize(payload, firing_only=False)
    assert len(all_tasks) == 2


def test_target_extraction_fallbacks():
    """测试目标提取规则兜底逻辑（当无 pod / node 时 fallback 到 job / service）。"""
    adapter = GenericAlertAdapter()
    # 带有 job 标签
    p1 = {"alertname": "JobFailed", "job": "batch-sync-job", "namespace": "cron"}
    t1 = adapter.normalize(p1)[0]
    assert t1.target_type == "k8s_pod"
    assert t1.target_name == "batch-sync-job"
    assert t1.namespace == "cron"

    # 带有 service 标签
    p2 = {"alertname": "ServiceDown", "service": "redis-sentinel"}
    t2 = adapter.normalize(p2)[0]
    assert t2.target_type == "k8s_pod"
    assert t2.target_name == "redis-sentinel"
    assert t2.namespace == "default"

    # 完全没有任何实体标识
    p3 = {"alertname": "MysteryAlert"}
    t3 = adapter.normalize(p3)[0]
    assert t3.target_type == "k8s_pod"
    assert t3.target_name == "unknown-service"
    assert t3.namespace == "default"


def test_custom_adapter_registration():
    """测试 NormalizerRegistry 自定义适配器注册与优先拦截。"""
    class MockCustomAdapter(BaseAlertAdapter):
        def can_handle(self, payload: dict) -> bool:
            return payload.get("source_vendor") == "datadog"

        def normalize(self, payload: dict, firing_only: bool = True):
            return [
                DiagnosticTask(
                    source="generic",
                    target_type="linux_node",
                    target_name=payload.get("host", "unknown"),
                    symptoms=payload.get("event_title", "DD Alert"),
                    fingerprint="1234567890abcdef",
                )
            ]

    registry = NormalizerRegistry()
    custom = MockCustomAdapter()
    # 插入到最前面以获取最高优先级
    registry._adapters.insert(0, custom)

    dd_payload = {"source_vendor": "datadog", "host": "datadog-agent-01", "event_title": "Host Out of Disk"}
    tasks = registry.normalize(dd_payload)
    assert len(tasks) == 1
    assert tasks[0].target_name == "datadog-agent-01"
    assert tasks[0].fingerprint == "1234567890abcdef"


def test_default_normalizer_singleton():
    """测试全局默认归一化解析器单例。"""
    n1 = get_default_normalizer()
    n2 = get_default_normalizer()
    assert n1 is n2

