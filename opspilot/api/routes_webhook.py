import logging
from typing import List
from fastapi import APIRouter, BackgroundTasks, status
from opspilot.schemas.alert import AlertmanagerPayload, AlertWebhookResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["Webhook"])

def async_diagnostic_worker(task_id: str, target: str) -> None:
    """后台异步排障工作流处理函数（后续与 M03 状态机对接）"""
    logger.info(f"Starting async diagnostic workflow for task_id={task_id}, target={target}")
    try:
        # 后续与 M03 状态机对接执行自动化排障与分析
        logger.info(f"Async diagnostic worker completed successfully for task_id={task_id}")
    except Exception as e:
        logger.error(f"Error during async diagnostic worker for task_id={task_id}: {e}", exc_info=True)
        raise

@router.post(
    "/alertmanager",
    response_model=AlertWebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="接收并分发 Alertmanager 告警 Webhook"
)
async def receive_alertmanager_webhook(
    payload: AlertmanagerPayload,
    background_tasks: BackgroundTasks
) -> AlertWebhookResponse:
    logger.info(f"Received Alertmanager webhook: status={payload.status}, total_alerts={len(payload.alerts)}")
    tasks = payload.to_diagnostic_tasks()
    task_ids: List[str] = []

    for task in tasks:
        task_ids.append(task.task_id)
        background_tasks.add_task(async_diagnostic_worker, task.task_id, task.target_name)

    logger.info(f"Dispatched {len(tasks)} diagnostic tasks, task_ids={task_ids}")

    return AlertWebhookResponse(
        status="ok",
        message="Alerts received and dispatched for diagnostic",
        dispatched_count=len(tasks),
        task_ids=task_ids,
        tasks=tasks
    )
