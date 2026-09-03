import pytest
from opspilot.config import Settings
from opspilot.schemas.task import DiagnosticTask
from opspilot.schemas.alert import AlertWebhookResponse

def test_m02_config_defaults():
    settings = Settings()
    assert settings.ALERT_DEDUP_WINDOW_SECONDS == 300
    assert settings.ALERT_STORM_THRESHOLD == 50
    assert settings.ALERT_STORM_WINDOW_SECONDS == 60

def test_diagnostic_task_with_m02_fields():
    task = DiagnosticTask(
        target_type="k8s_pod",
        target_name="order-api",
        symptoms="Pod OOMKilled",
        fingerprint="a1b2c3d4e5f60718",
        duplicate_count=3,
        is_storm_aggregated=True
    )
    assert task.fingerprint == "a1b2c3d4e5f60718"
    assert task.duplicate_count == 3
    assert task.is_storm_aggregated is True

def test_diagnostic_task_defaults():
    task = DiagnosticTask(
        target_type="linux_node",
        target_name="192.168.100.136",
        symptoms="Disk full"
    )
    assert task.fingerprint is None
    assert task.duplicate_count == 0
    assert task.is_storm_aggregated is False

def test_alert_webhook_response_m02_fields():
    resp = AlertWebhookResponse(
        status="ok",
        message="Alerts processed",
        dispatched_count=2,
        deduplicated_count=5,
        storm_throttled_count=1,
        task_ids=["task-1", "task-2"],
        tasks=[]
    )
    assert resp.deduplicated_count == 5
    assert resp.storm_throttled_count == 1

def test_alert_webhook_response_defaults():
    resp = AlertWebhookResponse(
        status="ok",
        message="Alerts processed",
        dispatched_count=1
    )
    assert resp.deduplicated_count == 0
    assert resp.storm_throttled_count == 0
    assert resp.task_ids == []
    assert resp.tasks == []
