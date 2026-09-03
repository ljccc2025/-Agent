from opspilot.schemas.task import DiagnosticTask
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

    # 验证 Node 任务分类
    assert tasks[1].target_type == "linux_node"
    assert tasks[1].target_name == "192.168.1.101"
    assert tasks[1].namespace is None
