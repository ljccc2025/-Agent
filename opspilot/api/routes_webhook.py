from typing import Dict, Any, List
from fastapi import APIRouter, BackgroundTasks, status
from opspilot.schemas.alert import AlertmanagerPayload

router = APIRouter(prefix="/webhook", tags=["Webhook"])

def async_diagnostic_worker(task_id: str, target: str) -> None:
    """后台异步排障工作流处理函数（后续与 M03 状态机对接）"""
    pass

@router.post("/alertmanager", status_code=status.HTTP_200_OK)
async def receive_alertmanager_webhook(
    payload: AlertmanagerPayload,
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    tasks = payload.to_diagnostic_tasks()
    task_ids: List[str] = []

    for task in tasks:
        task_ids.append(task.task_id)
        background_tasks.add_task(async_diagnostic_worker, task.task_id, task.target_name)

    return {
        "status": "ok",
        "message": "Alerts received and dispatched for diagnostic",
        "dispatched_count": len(tasks),
        "task_ids": task_ids,
        "tasks": [t.model_dump() for t in tasks]
    }
