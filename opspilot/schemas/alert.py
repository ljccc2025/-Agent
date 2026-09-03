from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from opspilot.schemas.task import DiagnosticTask, generate_task_id, TargetType

class AlertItem(BaseModel):
    status: str = "firing"
    labels: Dict[str, Any] = Field(default_factory=dict)
    annotations: Dict[str, Any] = Field(default_factory=dict)

class AlertmanagerPayload(BaseModel):
    status: str = "firing"
    receiver: Optional[str] = None
    alerts: List[AlertItem] = Field(default_factory=list)

    def to_diagnostic_tasks(self, firing_only: bool = True) -> List[DiagnosticTask]:
        tasks: List[DiagnosticTask] = []
        for alert in self.alerts:
            # 过滤已恢复的告警
            if firing_only and alert.status == "resolved":
                continue

            labels = alert.labels or {}
            annos = alert.annotations or {}
            alertname = labels.get("alertname") or "UnknownAlert"

            pod = labels.get("pod")
            node_target = labels.get("instance") or labels.get("node") or labels.get("host")

            target_type: TargetType
            target_name: str
            namespace: Optional[str]

            # 区分 k8s_pod 与 linux_node
            if pod:
                target_type = "k8s_pod"
                target_name = str(pod)
                namespace = labels.get("namespace") or "default"
            elif node_target:
                target_type = "linux_node"
                # 如果包含端口（如 192.168.1.101:9100），清洗提取 host 部分
                host = str(node_target).split(":")[0]
                target_name = host if host else "unknown-node"
                namespace = None
            else:
                target_type = "k8s_pod"
                job = labels.get("job")
                target_name = str(job) if job else "unknown-service"
                namespace = labels.get("namespace") or "default"

            desc = annos.get("description") or annos.get("summary")
            symptoms = str(desc) if desc else f"Alert {alertname} fired"

            tasks.append(DiagnosticTask(
                task_id=generate_task_id("alert"),
                source="alertmanager",
                target_type=target_type,
                target_name=target_name,
                namespace=namespace,
                alert_name=alertname,
                alert_labels=labels,
                symptoms=symptoms
            ))
        return tasks


class AlertWebhookResponse(BaseModel):
    status: str = Field(default="ok", description="处理状态")
    message: str = Field(..., description="处理结果描述")
    dispatched_count: int = Field(..., description="分发的排障任务总数")
    deduplicated_count: int = Field(default=0, description="被去重防抖拦截的重复告警数")
    storm_throttled_count: int = Field(default=0, description="被风暴抑制器合并的告警数")
    task_ids: list[str] = Field(default_factory=list, description="分发的任务ID列表")
    tasks: list[DiagnosticTask] = Field(default_factory=list, description="生成的任务实体明细")

