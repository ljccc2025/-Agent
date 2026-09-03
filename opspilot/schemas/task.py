import uuid
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class DiagnosticTask(BaseModel):
    task_id: str = Field(default_factory=lambda: f"task-{uuid.uuid4().hex[:8]}", description="唯一任务追踪ID")
    source: str = Field(default="alertmanager", description="来源: alertmanager / cli / manual_api")
    target_type: str = Field(..., description="目标类型: k8s_pod / linux_node")
    target_name: str = Field(..., description="目标实体名称 (Pod名或主机IP)")
    namespace: Optional[str] = Field(default=None, description="K8s 命名空间")
    alert_name: Optional[str] = Field(default=None, description="触发告警规则名称")
    alert_labels: Dict[str, Any] = Field(default_factory=dict, description="关联告警标签集")
    symptoms: str = Field(..., description="故障初始表象描述")
