import uuid
from typing import Optional, Dict, Any, Literal
from pydantic import BaseModel, Field

TargetType = Literal["k8s_pod", "linux_node"]
TaskSource = Literal["alertmanager", "cli", "manual_api"]

def generate_task_id(prefix: str = "task") -> str:
    """生成唯一的任务追踪 ID"""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"

class DiagnosticTask(BaseModel):
    task_id: str = Field(default_factory=generate_task_id, description="唯一任务追踪ID")
    source: TaskSource = Field(default="alertmanager", description="来源: alertmanager / cli / manual_api")
    target_type: TargetType = Field(..., description="目标类型: k8s_pod / linux_node")
    target_name: str = Field(..., min_length=1, description="目标实体名称 (Pod名或主机IP)")
    namespace: Optional[str] = Field(default=None, description="K8s 命名空间")
    alert_name: Optional[str] = Field(default=None, description="触发告警规则名称")
    alert_labels: Dict[str, Any] = Field(default_factory=dict, description="关联告警标签集")
    symptoms: str = Field(..., min_length=1, description="故障初始表象描述")
    fingerprint: Optional[str] = Field(default=None, description="确定性告警指纹哈希")
    duplicate_count: int = Field(default=0, description="窗口期内被去重抑制的重复频次")
    is_storm_aggregated: bool = Field(default=False, description="是否由告警风暴聚合生成")
