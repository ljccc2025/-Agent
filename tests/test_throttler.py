import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytest

from opspilot.config import settings
from opspilot.schemas.task import DiagnosticTask
from opspilot.normalizer import (
    AlertStormThrottler,
    StormThrottleResult,
    get_default_throttler,
)
import opspilot.normalizer.throttler as throttler_module


def _make_task(
    idx: int,
    target_type: str = "k8s_pod",
    target_name: str = "payment-svc-0",
    namespace: str = "prod",
    alert_name: str = "PodMemoryHigh",
    symptoms: str = "High memory usage detected",
) -> DiagnosticTask:
    """辅助生成 DiagnosticTask 测试对象。"""
    return DiagnosticTask(
        task_id=f"task-test-{idx:04d}",
        source="alertmanager",
        target_type=target_type,
        target_name=target_name,
        namespace=namespace,
        alert_name=f"{alert_name}-{idx}",
        alert_labels={"severity": "warning", "instance": f"inst-{idx}"},
        symptoms=f"{symptoms} on {target_name} ({idx})",
    )


def test_package_exports():
    """验证 __init__.py 正确导出了 AlertStormThrottler, StormThrottleResult, get_default_throttler。"""
    assert AlertStormThrottler is throttler_module.AlertStormThrottler
    assert StormThrottleResult is throttler_module.StormThrottleResult
    assert get_default_throttler is throttler_module.get_default_throttler


def test_normal_volume_no_storm():
    """告警数在阈值内放行，is_storm=False，任务原样返回。"""
    throttler = AlertStormThrottler(threshold=50, window_seconds=60)
    tasks = [_make_task(i) for i in range(10)]

    result = throttler.process_tasks(tasks, current_time=1000.0)

    assert isinstance(result, StormThrottleResult)
    assert result.is_storm is False
    assert result.throttled_count == 0
    assert result.aggregated_count == 0
    assert result.storm_reason is None
    assert len(result.dispatched_tasks) == 10
    assert result.dispatched_tasks == tasks
    # 原任务标志不应被改变
    for t in result.dispatched_tasks:
        assert t.is_storm_aggregated is False


def test_storm_triggered_when_threshold_exceeded():
    """突发超过 50 条告警触发风暴模式，is_storm=True。"""
    throttler = AlertStormThrottler(threshold=50, window_seconds=60)
    tasks = [_make_task(i, target_name=f"pod-{i}") for i in range(55)]

    result = throttler.process_tasks(tasks, current_time=1000.0)

    assert result.is_storm is True
    assert result.storm_reason == "最近 60s 内告警量达到 55 条，触发风暴聚合限制（阈值 50）"
    assert len(result.dispatched_tasks) == 55
    assert result.aggregated_count == 55
    assert result.throttled_count == 0


def test_storm_aggregation_by_failure_domain():
    """同一 Pod 或主机的多个不同告警在风暴模式下被聚合成 1 个代表性任务，
    is_storm_aggregated=True，伴随告警记录在 storm_associated_alerts 中。"""
    throttler = AlertStormThrottler(threshold=50, window_seconds=60)
    # 60 条告警全部属于同一个 Pod
    tasks = [
        _make_task(
            i,
            target_type="k8s_pod",
            target_name="order-center-7d98b",
            namespace="production",
            alert_name=f"OrderAlert_{i}",
            symptoms="Service latency high",
        )
        for i in range(60)
    ]

    result = throttler.process_tasks(tasks, current_time=1000.0)

    assert result.is_storm is True
    assert result.aggregated_count == 1
    assert result.throttled_count == 59
    assert len(result.dispatched_tasks) == 1

    primary = result.dispatched_tasks[0]
    assert primary.is_storm_aggregated is True
    assert primary.target_name == "order-center-7d98b"
    assert primary.namespace == "production"
    assert primary.symptoms.startswith("[告警风暴聚合 - 归并60条告警] ")
    assert "Service latency high on order-center-7d98b (0)" in primary.symptoms

    # 伴随告警记录其余 59 个任务的 alert_name
    expected_associated = [f"OrderAlert_{i}-{i}" for i in range(1, 60)]
    assert primary.alert_labels.get("storm_associated_alerts") == expected_associated


def test_storm_multiple_domains_preserved():
    """风暴模式下不同 Pod / Node 各自保留一个聚合任务。"""
    throttler = AlertStormThrottler(threshold=50, window_seconds=60)

    # 3 个不同故障域，每个域 20 条告警，总计 60 条
    tasks_pod_a = [
        _make_task(i, target_type="k8s_pod", target_name="pod-a", namespace="ns-1")
        for i in range(20)
    ]
    tasks_pod_b = [
        _make_task(i, target_type="k8s_pod", target_name="pod-b", namespace="ns-2")
        for i in range(20, 40)
    ]
    tasks_node_c = [
        _make_task(
            i,
            target_type="linux_node",
            target_name="192.168.10.101",
            namespace=None,
            alert_name="NodeDiskFull",
            symptoms="Disk usage > 90%",
        )
        for i in range(40, 60)
    ]

    all_tasks = tasks_pod_a + tasks_pod_b + tasks_node_c
    result = throttler.process_tasks(all_tasks, current_time=1000.0)

    assert result.is_storm is True
    assert result.aggregated_count == 3
    assert result.throttled_count == 57
    assert len(result.dispatched_tasks) == 3

    # 验证各故障域代表性任务
    primary_a = result.dispatched_tasks[0]
    assert primary_a.target_name == "pod-a"
    assert primary_a.namespace == "ns-1"
    assert primary_a.is_storm_aggregated is True
    assert primary_a.symptoms.startswith("[告警风暴聚合 - 归并20条告警]")
    assert len(primary_a.alert_labels["storm_associated_alerts"]) == 19

    primary_b = result.dispatched_tasks[1]
    assert primary_b.target_name == "pod-b"
    assert primary_b.namespace == "ns-2"
    assert primary_b.is_storm_aggregated is True
    assert primary_b.symptoms.startswith("[告警风暴聚合 - 归并20条告警]")
    assert len(primary_b.alert_labels["storm_associated_alerts"]) == 19

    primary_c = result.dispatched_tasks[2]
    assert primary_c.target_type == "linux_node"
    assert primary_c.target_name == "192.168.10.101"
    assert primary_c.namespace is None
    assert primary_c.is_storm_aggregated is True
    assert primary_c.symptoms.startswith("[告警风暴聚合 - 归并20条告警]")
    assert len(primary_c.alert_labels["storm_associated_alerts"]) == 19


def test_sliding_window_recovery():
    """模拟时间推移超出 window_seconds 后，告警速率下降，风暴模式自动恢复为正常模式。"""
    throttler = AlertStormThrottler(threshold=50, window_seconds=60)

    # t=1000.0: 发送 40 条告警（正常，未达 50 阈值）
    tasks_batch1 = [_make_task(i) for i in range(40)]
    res1 = throttler.process_tasks(tasks_batch1, current_time=1000.0)
    assert res1.is_storm is False
    assert len(res1.dispatched_tasks) == 40

    # t=1020.0: 在窗口内又发送 15 条告警（累积 40 + 15 = 55 > 50 -> 触发风暴）
    tasks_batch2 = [_make_task(i + 40) for i in range(15)]
    res2 = throttler.process_tasks(tasks_batch2, current_time=1020.0)
    assert res2.is_storm is True
    assert res2.storm_reason == "最近 60s 内告警量达到 55 条，触发风暴聚合限制（阈值 50）"

    # t=1061.0: 距离 1000.0 超过 60s，batch1 的 40 条记录已过期淘汰
    # 当前历史剩余 batch2 的 15 条
    # 发送 10 条新告警：累积 15 + 10 = 25 <= 50 -> 恢复正常模式
    tasks_batch3 = [_make_task(i + 100) for i in range(10)]
    res3 = throttler.process_tasks(tasks_batch3, current_time=1061.0)
    assert res3.is_storm is False
    assert res3.throttled_count == 0
    assert len(res3.dispatched_tasks) == 10

    # t=1081.0: 距离 1020.0 超过 60s，batch2 已过期，此时历史剩余 batch3 (10条)
    # 发送 40 条：累积 10 + 40 = 50 <= 50 -> 依然是正常模式
    tasks_batch4 = [_make_task(i + 200) for i in range(40)]
    res4 = throttler.process_tasks(tasks_batch4, current_time=1081.0)
    assert res4.is_storm is False
    assert len(res4.dispatched_tasks) == 40

    # t=1145.0: 距离 1081.0 超过 60s，所有历史均已过期清空
    # 发送 50 条正好等于阈值 -> 正常模式
    tasks_batch5 = [_make_task(i + 300) for i in range(50)]
    res5 = throttler.process_tasks(tasks_batch5, current_time=1145.0)
    assert res5.is_storm is False
    assert len(res5.dispatched_tasks) == 50




def test_reset_clears_history():
    """清空历史记录后，后续告警重置为正常速率判定。"""
    throttler = AlertStormThrottler(threshold=50, window_seconds=60)

    # 发送 55 条触发风暴
    tasks = [_make_task(i) for i in range(55)]
    res1 = throttler.process_tasks(tasks, current_time=1000.0)
    assert res1.is_storm is True

    # 重置清空
    throttler.reset()
    assert len(throttler._history) == 0

    # 紧接着在同一时间点发送 5 条，应为正常放行
    tasks_small = [_make_task(i + 100) for i in range(5)]
    res2 = throttler.process_tasks(tasks_small, current_time=1000.0)
    assert res2.is_storm is False
    assert len(res2.dispatched_tasks) == 5


def test_empty_tasks_handled_gracefully():
    """验证传入空任务列表时正常返回且不报错。"""
    throttler = AlertStormThrottler(threshold=50, window_seconds=60)
    res = throttler.process_tasks([], current_time=1000.0)
    assert res.is_storm is False
    assert res.dispatched_tasks == []
    assert res.throttled_count == 0
    assert res.aggregated_count == 0


def test_default_timestamp_is_now():
    """验证不传 current_time 时使用真实时间戳。"""
    throttler = AlertStormThrottler(threshold=50, window_seconds=60)
    t_before = time.time()
    res = throttler.process_tasks([_make_task(1)])
    t_after = time.time()

    assert res.is_storm is False
    assert len(throttler._history) == 1
    record_time, task_id = throttler._history[0]
    assert t_before <= record_time <= t_after


def test_multithreaded_throttler_safety():
    """多线程并发写入，无数据竞态。"""
    throttler = AlertStormThrottler(threshold=100, window_seconds=60)
    num_threads = 10
    tasks_per_thread = 20  # 总计 200 个任务

    def worker(thread_id: int):
        thread_tasks = [
            _make_task(
                thread_id * 100 + j,
                target_type="k8s_pod",
                target_name=f"pod-{thread_id % 3}",
                namespace="default",
            )
            for j in range(tasks_per_thread)
        ]
        return throttler.process_tasks(thread_tasks)

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker, i) for i in range(num_threads)]
        results = [f.result() for f in as_completed(futures)]

    # 所有线程都执行成功
    assert len(results) == num_threads
    # 历史记录总数必须精确等于 200
    with throttler._lock:
        assert len(throttler._history) == 200


def test_default_throttler_singleton():
    """单例模式验证，正确使用 settings 中的配置。"""
    throttler_module._default_throttler = None

    t1 = get_default_throttler()
    t2 = get_default_throttler()

    assert isinstance(t1, AlertStormThrottler)
    assert t1 is t2
    assert t1.threshold == settings.ALERT_STORM_THRESHOLD
    assert t1.window_seconds == settings.ALERT_STORM_WINDOW_SECONDS
