import pytest
from pydantic import ValidationError
from opspilot.schemas.task import DiagnosticTask, generate_task_id
from opspilot.schemas.alert import AlertmanagerPayload, AlertItem

def test_alertmanager_payload_to_diagnostic_tasks():
    payload = AlertmanagerPayload(
        status="firing",
        alerts=[
            AlertItem(
                status="firing",
                labels={"alertname": "KubePodCrashLooping", "pod": "order-api", "namespace": "prod"},
                annotations={"description": "Pod is in CrashLoopBackOff"}
            ),
            AlertItem(
                status="firing",
                labels={"alertname": "NodeDiskPressure", "instance": "192.168.1.101"},
                annotations={"summary": "Root disk usage > 95%"}
            )
        ]
    )
    tasks = payload.to_diagnostic_tasks()
    assert len(tasks) == 2
    
    # 验证 Pod 任务分类
    assert tasks[0].target_type == "k8s_pod"
    assert tasks[0].target_name == "order-api"
    assert tasks[0].namespace == "prod"
    assert tasks[0].alert_name == "KubePodCrashLooping"
    assert tasks[0].task_id.startswith("alert-")

    # 验证 Node 任务分类
    assert tasks[1].target_type == "linux_node"
    assert tasks[1].target_name == "192.168.1.101"
    assert tasks[1].namespace is None
    assert tasks[1].task_id.startswith("alert-")

def test_alert_schemas_none_and_empty_handling():
    payload = AlertmanagerPayload(
        status="firing",
        alerts=[
            AlertItem(
                status="firing",
                labels={"alertname": "PodNoneAlert", "pod": None},
                annotations={}
            ),
            AlertItem(
                status="firing",
                labels={"alertname": "InstanceNoneAlert", "instance": None},
                annotations={}
            ),
            AlertItem(
                status="firing",
                labels={"alertname": "EmptyLabelsAlert"},
                annotations={}
            ),
            AlertItem(
                status="firing",
                labels={"alertname": "JobSpecifiedAlert", "pod": None, "job": "payment-service"},
                annotations={}
            )
        ]
    )
    tasks = payload.to_diagnostic_tasks()
    assert len(tasks) == 4
    
    assert tasks[0].target_type == "k8s_pod"
    assert tasks[0].target_name == "unknown-service"
    assert tasks[0].namespace == "default"

    assert tasks[1].target_type == "k8s_pod"
    assert tasks[1].target_name == "unknown-service"
    assert tasks[1].namespace == "default"

    assert tasks[2].target_type == "k8s_pod"
    assert tasks[2].target_name == "unknown-service"

    assert tasks[3].target_type == "k8s_pod"
    assert tasks[3].target_name == "payment-service"

def test_instance_with_port_cleaned():
    payload = AlertmanagerPayload(
        status="firing",
        alerts=[
            AlertItem(
                status="firing",
                labels={"alertname": "NodeCpuUsageHigh", "instance": "10.0.0.1:9100"},
                annotations={"summary": "CPU usage > 90%"}
            )
        ]
    )
    tasks = payload.to_diagnostic_tasks()
    assert len(tasks) == 1
    assert tasks[0].target_type == "linux_node"
    assert tasks[0].target_name == "10.0.0.1"
    assert tasks[0].namespace is None

def test_resolved_alert_filtering():
    payload = AlertmanagerPayload(
        status="firing",
        alerts=[
            AlertItem(
                status="firing",
                labels={"alertname": "HighMemory", "instance": "192.168.1.10"},
                annotations={"description": "Mem high"}
            ),
            AlertItem(
                status="resolved",
                labels={"alertname": "HighCPU", "instance": "192.168.1.11"},
                annotations={"description": "CPU recovered"}
            )
        ]
    )
    # 默认 firing_only=True，过滤已恢复告警
    tasks_firing = payload.to_diagnostic_tasks()
    assert len(tasks_firing) == 1
    assert tasks_firing[0].alert_name == "HighMemory"

    # 显式 firing_only=False，不过滤
    tasks_all = payload.to_diagnostic_tasks(firing_only=False)
    assert len(tasks_all) == 2

def test_missing_annotations_fallback_symptoms():
    payload = AlertmanagerPayload(
        status="firing",
        alerts=[
            AlertItem(
                status="firing",
                labels={"alertname": "DiskFull", "instance": "192.168.1.20"},
                annotations={}
            )
        ]
    )
    tasks = payload.to_diagnostic_tasks()
    assert len(tasks) == 1
    assert tasks[0].symptoms == "Alert DiskFull fired"

def test_empty_alerts_returns_empty_tasks():
    payload = AlertmanagerPayload(alerts=[])
    assert payload.to_diagnostic_tasks() == []

def test_diagnostic_task_literal_and_min_length_validation():
    # 校验合法枚举及默认值
    task = DiagnosticTask(
        target_type="k8s_pod",
        target_name="order-api",
        symptoms="Pod crash looping"
    )
    assert task.source == "alertmanager"
    assert task.task_id.startswith("task-")

    # 校验非法 target_type
    with pytest.raises(ValidationError):
        DiagnosticTask(
            target_type="invalid_type",  # type: ignore
            target_name="order-api",
            symptoms="Pod crash looping"
        )

    # 校验非法 source
    with pytest.raises(ValidationError):
        DiagnosticTask(
            source="unknown_source",  # type: ignore
            target_type="k8s_pod",
            target_name="order-api",
            symptoms="Pod crash looping"
        )

    # 校验 target_name 长度限制 (min_length=1)
    with pytest.raises(ValidationError):
        DiagnosticTask(
            target_type="k8s_pod",
            target_name="",
            symptoms="Pod crash looping"
        )

    # 校验 symptoms 长度限制 (min_length=1)
    with pytest.raises(ValidationError):
        DiagnosticTask(
            target_type="k8s_pod",
            target_name="order-api",
            symptoms=""
        )

def test_generate_task_id():
    custom_id = generate_task_id("custom")
    assert custom_id.startswith("custom-")
    assert len(custom_id) > 7
