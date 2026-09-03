import logging
from typing import Optional
from fastapi import APIRouter, BackgroundTasks, status
from pydantic import BaseModel, Field
from opspilot.schemas.task import DiagnosticTask, TargetType, generate_task_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Diagnose"])

class ManualDiagnoseRequest(BaseModel):
    """交互式手动排障请求体"""
    target_type: TargetType = Field(..., description="目标类型: k8s_pod / linux_node")
    target_name: str = Field(..., min_length=1, description="目标实体名称 (Pod名或主机IP)")
    namespace: Optional[str] = Field(default="default", description="K8s 命名空间 (仅针对 k8s_pod)")
    symptoms: str = Field(..., min_length=1, description="故障初始表象描述")

class ManualDiagnoseResponse(BaseModel):
    """交互式手动排障响应体"""
    status: str = Field(default="dispatched", description="任务分发状态")
    task_id: str = Field(..., description="唯一任务追踪ID")
    message: str = Field(..., description="操作响应消息")
    task: DiagnosticTask = Field(..., description="生成的诊断任务实体")

def async_manual_diagnostic_worker(task_id: str, target: str) -> None:
    """后台异步手动排障工作流处理函数（后续与 M03 状态机对接）"""
    logger.info("Starting async manual diagnostic workflow for task_id=%s, target=%s", task_id, target)
    try:
        # 后续与 M03 状态机对接执行自动化排障与根因分析
        logger.info("Async manual diagnostic worker completed successfully for task_id=%s", task_id)
    except Exception as e:
        logger.error("Error during async manual diagnostic worker for task_id=%s: %s", task_id, e, exc_info=True)
        raise

@router.post(
    "/diagnose",
    response_model=ManualDiagnoseResponse,
    status_code=status.HTTP_200_OK,
    summary="触发交互式主动排查任务"
)
async def trigger_manual_diagnose(
    req: ManualDiagnoseRequest,
    background_tasks: BackgroundTasks
) -> ManualDiagnoseResponse:
    """
    接收 SRE / 运维人员交互式发起的排障请求，生成标准化 DiagnosticTask 并异步分发。
    """
    logger.info(
        "Received manual diagnose request: target_type=%s, target_name=%s, namespace=%s",
        req.target_type, req.target_name, req.namespace
    )

    # 针对集群级/主机级 linux_node 实体，命名空间强制规范化为 None
    normalized_namespace = None if req.target_type == "linux_node" else (req.namespace or "default")

    task_id = generate_task_id("manual")
    task = DiagnosticTask(
        task_id=task_id,
        source="manual_api",
        target_type=req.target_type,
        target_name=req.target_name,
        namespace=normalized_namespace,
        symptoms=req.symptoms
    )

    # 通过 BackgroundTasks 调度非阻塞异步排障 Worker
    background_tasks.add_task(async_manual_diagnostic_worker, task.task_id, task.target_name)
    logger.info("Dispatched manual diagnostic task: task_id=%s, target=%s", task.task_id, task.target_name)

    return ManualDiagnoseResponse(
        status="dispatched",
        task_id=task.task_id,
        message=f"Diagnostic task {task.task_id} dispatched successfully",
        task=task
    )
