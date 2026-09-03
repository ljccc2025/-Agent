import uuid
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from opspilot.schemas.task import DiagnosticTask

class AlertItem(BaseModel):
    status: str = "firing"
    labels: Dict[str, Any] = Field(default_factory=dict)
    annotations: Dict[str, Any] = Field(default_factory=dict)

class AlertmanagerPayload(BaseModel):
    status: str = "firing"
    receiver: Optional[str] = None
    alerts: List[AlertItem] = Field(default_factory=list)

    def to_diagnostic_tasks(self) -> List[DiagnosticTask]:
        tasks: List[DiagnosticTask] = []
        for alert in self.alerts:
            labels = alert.labels
            annos = alert.annotations
            alertname = labels.get("alertname", "UnknownAlert")

            # 区分 k8s_pod 与 linux_node
            if "pod" in labels:
                target_type = "k8s_pod"
                target_name = labels["pod"]
                namespace = labels.get("namespace", "default")
            elif "instance" in labels or "node" in labels or "host" in labels:
                target_type = "linux_node"
                target_name = labels.get("instance") or labels.get("node") or labels.get("host")
                namespace = None
            else:
                target_type = "k8s_pod"
                target_name = labels.get("job", "unknown-service")
                namespace = labels.get("namespace", "default")

            symptoms = annos.get("description") or annos.get("summary") or f"Alert {alertname} fired"

            tasks.append(DiagnosticTask(
                task_id=f"alert-{uuid.uuid4().hex[:8]}",
                source="alertmanager",
                target_type=target_type,
                target_name=target_name,
                namespace=namespace,
                alert_name=alertname,
                alert_labels=labels,
                symptoms=symptoms
            ))
        return tasks
