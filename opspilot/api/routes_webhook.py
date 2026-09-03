import logging
from typing import List, Dict, Any, Union
from fastapi import APIRouter, BackgroundTasks, Request, status, HTTPException

from opspilot.schemas.alert import AlertmanagerPayload, AlertWebhookResponse
from opspilot.schemas.task import DiagnosticTask
from opspilot.normalizer import (
    get_default_normalizer,
    get_default_deduplicator,
    get_default_throttler,
    generate_alert_fingerprint,
)

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


def _process_alert_pipeline(
    raw_dict: Dict[str, Any],
    background_tasks: BackgroundTasks,
    source_name: str,
) -> AlertWebhookResponse:
    """通用告警处理流水线：归一化 -> 防抖去重 -> 突发风暴抑制 -> 异步工作流分发"""
    normalizer = get_default_normalizer()
    deduplicator = get_default_deduplicator()
    throttler = get_default_throttler()

    # 1. 异构告警归一化
    tasks = normalizer.normalize(raw_dict, firing_only=True)

    # 2. 告警指纹校验与防抖去重
    new_tasks: List[DiagnosticTask] = []
    deduplicated_count = 0

    for task in tasks:
        # 兜底确保指纹已计算生成
        if not task.fingerprint:
            task.fingerprint = generate_alert_fingerprint(
                alertname=task.alert_name or "UnknownAlert",
                target_type=task.target_type,
                target_name=task.target_name,
                namespace=task.namespace,
                labels=task.alert_labels,
            )

        dedup_res = deduplicator.process(task.fingerprint)
        if dedup_res.is_duplicate:
            deduplicated_count += 1
            logger.info(
                f"Alert deduplicated and suppressed: fingerprint={task.fingerprint}, "
                f"alertname={task.alert_name}, target={task.target_name}, "
                f"duplicate_count={dedup_res.duplicate_count}"
            )
        else:
            task.duplicate_count = dedup_res.duplicate_count
            task.fingerprint = dedup_res.fingerprint
            new_tasks.append(task)

    # 3. 突发风暴限流抑制
    storm_throttled_count = 0
    tasks_to_dispatch: List[DiagnosticTask] = []

    if new_tasks:
        storm_res = throttler.process_tasks(new_tasks)
        if storm_res.is_storm:
            tasks_to_dispatch = storm_res.dispatched_tasks
            storm_throttled_count += storm_res.throttled_count
            logger.warning(
                f"Alert storm triggered and aggregated: reason='{storm_res.storm_reason}', "
                f"original={len(new_tasks)}, dispatched={len(tasks_to_dispatch)}, "
                f"throttled={storm_res.throttled_count}"
            )
        else:
            tasks_to_dispatch = storm_res.dispatched_tasks
    else:
        tasks_to_dispatch = []

    # 4. 后台异步任务派发
    task_ids: List[str] = []
    for task in tasks_to_dispatch:
        task_ids.append(task.task_id)
        background_tasks.add_task(async_diagnostic_worker, task.task_id, task.target_name)

    logger.info(
        f"Completed {source_name} webhook processing: "
        f"raw_alerts={len(tasks)}, dispatched={len(tasks_to_dispatch)}, "
        f"deduplicated={deduplicated_count}, storm_throttled={storm_throttled_count}, "
        f"task_ids={task_ids}"
    )

    return AlertWebhookResponse(
        status="ok",
        message="Alerts received and dispatched for diagnostic",
        dispatched_count=len(tasks_to_dispatch),
        deduplicated_count=deduplicated_count,
        storm_throttled_count=storm_throttled_count,
        task_ids=task_ids,
        tasks=tasks_to_dispatch,
    )


@router.post(
    "/alertmanager",
    response_model=AlertWebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="接收并分发 Alertmanager 告警 Webhook",
)
async def receive_alertmanager_webhook(
    payload: Union[AlertmanagerPayload, Dict[str, Any]],
    background_tasks: BackgroundTasks,
    request: Request,
) -> AlertWebhookResponse:
    """接收 Alertmanager Webhook 告警，执行归一化、去重防抖与风暴抑制后派发排障任务。"""
    if isinstance(payload, AlertmanagerPayload):
        raw_dict = payload.model_dump()
    elif isinstance(payload, dict):
        if "alerts" in payload and not isinstance(payload["alerts"], list):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Invalid payload: 'alerts' field must be a list",
            )
        raw_dict = payload
    else:
        raw_dict = dict(payload)

    status_str = raw_dict.get("status", "firing")
    alerts_count = len(raw_dict.get("alerts", [])) if isinstance(raw_dict.get("alerts"), list) else 1
    logger.info(f"Received Alertmanager webhook: status={status_str}, total_alerts={alerts_count}")

    return _process_alert_pipeline(raw_dict, background_tasks, source_name="Alertmanager")


@router.post(
    "/grafana",
    response_model=AlertWebhookResponse,
    status_code=status.HTTP_200_OK,
    summary="接收并分发 Grafana 告警 Webhook",
)
async def receive_grafana_webhook(
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks,
    request: Request,
) -> AlertWebhookResponse:
    """接收 Grafana Alerting Webhook 告警，执行归一化、去重防抖与风暴抑制后派发排障任务。"""
    state_str = payload.get("state") or payload.get("status") or "unknown"
    logger.info(f"Received Grafana webhook: state={state_str}")

    return _process_alert_pipeline(payload, background_tasks, source_name="Grafana")
