import time
import threading
from collections import deque
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

from opspilot.schemas.task import DiagnosticTask


class StormThrottleResult(BaseModel):
    """告警风暴限流抑制结果模型。"""
    is_storm: bool = Field(..., description="是否触发了告警风暴保护")
    dispatched_tasks: List[DiagnosticTask] = Field(..., description="实际派发的任务列表（风暴下已聚合）")
    throttled_count: int = Field(default=0, description="被抑制合并的告警数量")
    aggregated_count: int = Field(default=0, description="聚合生成的代表性任务数量")
    storm_reason: Optional[str] = Field(default=None, description="风暴触发原因说明")


class AlertStormThrottler:
    """告警风暴突发聚合与限流抑制器。"""

    def __init__(self, threshold: int = 50, window_seconds: int = 60):
        self.threshold = threshold
        self.window_seconds = window_seconds
        self._history = deque()  # (timestamp, task_id)
        self._lock = threading.Lock()

    def process_tasks(
        self,
        tasks: List[DiagnosticTask],
        current_time: Optional[float] = None
    ) -> StormThrottleResult:
        """处理批量告警任务，进行速率检测与故障域风暴聚合（线程安全）。"""
        now = current_time if current_time is not None else time.time()

        with self._lock:
            # 清理超出滑动窗口的过期时间戳
            while self._history and self._history[0][0] < now - self.window_seconds:
                self._history.popleft()

            # 当前窗口内累积告警数
            total_recent = len(self._history) + len(tasks)

            # 将当前任务记录入滑动窗口历史
            for task in tasks:
                self._history.append((now, task.task_id))

            # 正常情况：累积数未超过阈值
            if total_recent <= self.threshold:
                return StormThrottleResult(
                    is_storm=False,
                    dispatched_tasks=tasks,
                    throttled_count=0,
                    aggregated_count=0,
                    storm_reason=None,
                )

            # 风暴触发：按故障域聚合
            domain_groups: Dict[str, List[DiagnosticTask]] = {}
            for task in tasks:
                domain_key = f"{task.target_type}:{task.namespace or ''}:{task.target_name}"
                if domain_key not in domain_groups:
                    domain_groups[domain_key] = []
                domain_groups[domain_key].append(task)

            dispatched_tasks: List[DiagnosticTask] = []
            for domain_key, domain_tasks in domain_groups.items():
                primary = domain_tasks[0].model_copy(deep=True)
                primary.is_storm_aggregated = True
                primary.symptoms = (
                    f"[告警风暴聚合 - 归并{len(domain_tasks)}条告警] {primary.symptoms}"
                )
                associated_alerts = [
                    t.alert_name for t in domain_tasks[1:] if t.alert_name is not None
                ]
                primary.alert_labels["storm_associated_alerts"] = associated_alerts
                dispatched_tasks.append(primary)

            throttled_count = len(tasks) - len(dispatched_tasks)
            aggregated_count = len(dispatched_tasks)
            storm_reason = (
                f"最近 {self.window_seconds}s 内告警量达到 {total_recent} 条，"
                f"触发风暴聚合限制（阈值 {self.threshold}）"
            )

            return StormThrottleResult(
                is_storm=True,
                dispatched_tasks=dispatched_tasks,
                throttled_count=throttled_count,
                aggregated_count=aggregated_count,
                storm_reason=storm_reason,
            )

    def reset(self) -> None:
        """清空历史记录。"""
        with self._lock:
            self._history.clear()


_default_throttler: Optional[AlertStormThrottler] = None
_throttler_lock = threading.Lock()


def get_default_throttler() -> AlertStormThrottler:
    """获取全局默认风暴抑制器单例（结合 settings.ALERT_STORM_THRESHOLD 与 settings.ALERT_STORM_WINDOW_SECONDS）。"""
    global _default_throttler
    if _default_throttler is None:
        with _throttler_lock:
            if _default_throttler is None:
                from opspilot.config import settings
                _default_throttler = AlertStormThrottler(
                    threshold=settings.ALERT_STORM_THRESHOLD,
                    window_seconds=settings.ALERT_STORM_WINDOW_SECONDS,
                )
    return _default_throttler
