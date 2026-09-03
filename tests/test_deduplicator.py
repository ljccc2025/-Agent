import time
from concurrent.futures import ThreadPoolExecutor, as_completed
import pytest
from opspilot.config import settings
from opspilot.normalizer import (
    AlertDeduplicator,
    DeduplicationResult,
    get_default_deduplicator,
)
import opspilot.normalizer.deduplicator as deduplicator_module


def test_package_exports():
    """验证 __init__.py 正确导出了 AlertDeduplicator, DeduplicationResult, get_default_deduplicator。"""
    assert AlertDeduplicator is deduplicator_module.AlertDeduplicator
    assert DeduplicationResult is deduplicator_module.DeduplicationResult
    assert get_default_deduplicator is deduplicator_module.get_default_deduplicator


def test_first_alert_is_not_duplicate():
    """首次告警放行：is_duplicate=False, duplicate_count=0。"""
    dedup = AlertDeduplicator(window_seconds=300)
    result = dedup.process("fp_test_001", timestamp=1000.0)

    assert isinstance(result, DeduplicationResult)
    assert result.fingerprint == "fp_test_001"
    assert result.is_duplicate is False
    assert result.duplicate_count == 0
    assert result.first_seen == 1000.0
    assert result.last_seen == 1000.0

    # 验证 get_entry 返回快照
    entry = dedup.get_entry("fp_test_001")
    assert entry is not None
    assert entry.fingerprint == "fp_test_001"
    assert entry.duplicate_count == 0
    assert entry.first_seen == 1000.0
    assert entry.last_seen == 1000.0


def test_sliding_window_duplicate_suppression():
    """在窗口期内多次 process 同一指纹，后续调用返回 is_duplicate=True，且 duplicate_count 逐次递增。"""
    dedup = AlertDeduplicator(window_seconds=300)

    # 第 1 次：首次放行
    r1 = dedup.process("fp_alert_002", timestamp=1000.0)
    assert r1.is_duplicate is False
    assert r1.duplicate_count == 0
    assert r1.first_seen == 1000.0
    assert r1.last_seen == 1000.0

    # 第 2 次（50秒后，未超期）：防抖拦截，计数为 1
    r2 = dedup.process("fp_alert_002", timestamp=1050.0)
    assert r2.is_duplicate is True
    assert r2.duplicate_count == 1
    assert r2.first_seen == 1000.0
    assert r2.last_seen == 1050.0

    # 第 3 次（又过了 100秒，未超期）：防抖拦截，计数为 2
    r3 = dedup.process("fp_alert_002", timestamp=1150.0)
    assert r3.is_duplicate is True
    assert r3.duplicate_count == 2
    assert r3.first_seen == 1000.0
    assert r3.last_seen == 1150.0

    # 第 4 次（距离上次 last_seen 1150 过了 200秒，未超过 300秒滑动窗口）：防抖拦截，计数为 3
    r4 = dedup.process("fp_alert_002", timestamp=1350.0)
    assert r4.is_duplicate is True
    assert r4.duplicate_count == 3
    assert r4.first_seen == 1000.0
    assert r4.last_seen == 1350.0

    # 验证最终 entry
    entry = dedup.get_entry("fp_alert_002")
    assert entry is not None
    assert entry.duplicate_count == 3
    assert entry.first_seen == 1000.0
    assert entry.last_seen == 1350.0


def test_expired_alert_becomes_new():
    """模拟经过超过 window_seconds 时间后，再次到达被视为新告警（is_duplicate=False, duplicate_count=0）。"""
    dedup = AlertDeduplicator(window_seconds=300)

    # 首次告警
    r1 = dedup.process("fp_alert_003", timestamp=1000.0)
    assert r1.is_duplicate is False
    assert r1.duplicate_count == 0

    # 窗口内重复
    r2 = dedup.process("fp_alert_003", timestamp=1050.0)
    assert r2.is_duplicate is True
    assert r2.duplicate_count == 1
    assert r2.last_seen == 1050.0

    # 距离上次 last_seen(1050.0) 过了 301秒（1351.0 > 1050.0 + 300），视为新一轮告警
    r3 = dedup.process("fp_alert_003", timestamp=1351.0)
    assert r3.is_duplicate is False
    assert r3.duplicate_count == 0
    assert r3.first_seen == 1351.0
    assert r3.last_seen == 1351.0

    # 新一轮窗口期内的重复告警
    r4 = dedup.process("fp_alert_003", timestamp=1400.0)
    assert r4.is_duplicate is True
    assert r4.duplicate_count == 1
    assert r4.first_seen == 1351.0
    assert r4.last_seen == 1400.0


def test_different_fingerprints_independent():
    """不同指纹互不干扰，独立计数。"""
    dedup = AlertDeduplicator(window_seconds=300)

    res_a1 = dedup.process("fp_a", timestamp=1000.0)
    res_b1 = dedup.process("fp_b", timestamp=1010.0)

    assert res_a1.is_duplicate is False
    assert res_a1.duplicate_count == 0
    assert res_b1.is_duplicate is False
    assert res_b1.duplicate_count == 0

    res_a2 = dedup.process("fp_a", timestamp=1020.0)
    assert res_a2.is_duplicate is True
    assert res_a2.duplicate_count == 1

    # fp_b 不受 fp_a 影响
    res_b2 = dedup.process("fp_b", timestamp=1030.0)
    assert res_b2.is_duplicate is True
    assert res_b2.duplicate_count == 1

    res_c1 = dedup.process("fp_c", timestamp=1040.0)
    assert res_c1.is_duplicate is False
    assert res_c1.duplicate_count == 0

    assert dedup.get_entry("fp_a").duplicate_count == 1
    assert dedup.get_entry("fp_b").duplicate_count == 1
    assert dedup.get_entry("fp_c").duplicate_count == 0
    assert dedup.get_entry("fp_nonexistent") is None


def test_purge_expired_entries():
    """验证 purge_expired 能正确清除超期数据并返回清除数。"""
    dedup = AlertDeduplicator(window_seconds=300)

    dedup.process("fp_old_1", timestamp=1000.0)
    dedup.process("fp_old_2", timestamp=1050.0)
    dedup.process("fp_fresh", timestamp=1300.0)

    # 在 t=1360.0 时：
    # fp_old_1 (last_seen=1000): 1360 - 1000 = 360 > 300 (过期)
    # fp_old_2 (last_seen=1050): 1360 - 1050 = 310 > 300 (过期)
    # fp_fresh (last_seen=1300): 1360 - 1300 = 60 <= 300 (未过期)
    purged_count = dedup.purge_expired(current_time=1360.0)
    assert purged_count == 2

    assert dedup.get_entry("fp_old_1") is None
    assert dedup.get_entry("fp_old_2") is None
    assert dedup.get_entry("fp_fresh") is not None

    # 再次在同时间清理，应返回 0
    assert dedup.purge_expired(current_time=1360.0) == 0

    # 推进时间到 1601.0，fp_fresh 也过期
    assert dedup.purge_expired(current_time=1601.0) == 1
    assert dedup.get_entry("fp_fresh") is None


def test_max_entries_eviction():
    """验证超过最大容量时能安全淘汰且不抛异常。"""
    max_entries = 5
    dedup = AlertDeduplicator(window_seconds=300, max_entries=max_entries)

    # 插入 5 条数据
    for i in range(5):
        dedup.process(f"fp_{i}", timestamp=1000.0 + i * 10)

    for i in range(5):
        assert dedup.get_entry(f"fp_{i}") is not None

    # 插入第 6 条数据（超容），应该触发淘汰，不应抛出异常
    res = dedup.process("fp_new_5", timestamp=1100.0)
    assert res.is_duplicate is False
    assert dedup.get_entry("fp_new_5") is not None

    # 缓存条目数不应超过 max_entries
    # 最早的 fp_0 (last_seen 最小) 应该已经被淘汰
    assert dedup.get_entry("fp_0") is None

    # 再次插入多条数据，确保容量稳态
    for i in range(6, 15):
        dedup.process(f"fp_batch_{i}", timestamp=1200.0 + i)

    # 当前缓存大小依然受限
    assert len(dedup._cache) <= max_entries


def test_clear_cache():
    """验证 clear() 能完全清空所有缓存。"""
    dedup = AlertDeduplicator(window_seconds=300)
    dedup.process("fp_1", timestamp=1000.0)
    dedup.process("fp_2", timestamp=1000.0)

    assert dedup.get_entry("fp_1") is not None
    assert dedup.get_entry("fp_2") is not None

    dedup.clear()

    assert dedup.get_entry("fp_1") is None
    assert dedup.get_entry("fp_2") is None
    assert len(dedup._cache) == 0


def test_default_timestamp_is_now():
    """验证不传 timestamp 时自动使用当前真实时间。"""
    dedup = AlertDeduplicator(window_seconds=300)
    t_before = time.time()
    res = dedup.process("fp_realtime")
    t_after = time.time()

    assert res.is_duplicate is False
    assert t_before <= res.first_seen <= t_after
    assert t_before <= res.last_seen <= t_after


def test_multithreaded_concurrency_safety():
    """使用 ThreadPoolExecutor 启动 20 个并发线程同时对相同及不同指纹调用 process，验证无死锁、无异常且计数精确无竞态。"""
    dedup = AlertDeduplicator(window_seconds=300, max_entries=5000)
    num_threads = 20
    repeats_per_thread = 50
    total_calls_shared = num_threads * repeats_per_thread  # 1000 次针对同一个指纹

    shared_fp = "fp_concurrent_shared"

    def worker_shared(_):
        results = []
        for _ in range(repeats_per_thread):
            # 不传 timestamp，以真实并发时间执行
            res = dedup.process(shared_fp)
            results.append(res)
        return results

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_shared, i) for i in range(num_threads)]
        all_shared_results = []
        for f in as_completed(futures):
            all_shared_results.extend(f.result())

    # 针对同一个指纹，首次 process 必须且只能有 1 次 is_duplicate=False
    non_duplicates = [r for r in all_shared_results if not r.is_duplicate]
    duplicates = [r for r in all_shared_results if r.is_duplicate]

    assert len(non_duplicates) == 1, f"Expected 1 non-duplicate, got {len(non_duplicates)}"
    assert len(duplicates) == total_calls_shared - 1

    # 最终 entry 的 duplicate_count 必须准确等于 total_calls_shared - 1
    final_entry = dedup.get_entry(shared_fp)
    assert final_entry is not None
    assert final_entry.duplicate_count == total_calls_shared - 1

    # 混合测试：多个线程并发写入大量不同指纹，验证无死锁与异常
    def worker_distinct(worker_id):
        for j in range(20):
            fp = f"fp_thread_{worker_id}_{j}"
            res = dedup.process(fp)
            assert res.is_duplicate is False

    with ThreadPoolExecutor(max_workers=num_threads) as executor:
        futures = [executor.submit(worker_distinct, i) for i in range(num_threads)]
        for f in as_completed(futures):
            f.result()  # 若有异常在此处抛出


def test_default_deduplicator_singleton():
    """验证 get_default_deduplicator 单例模式工作正常。"""
    # 重置单例以防受之前测试干扰
    deduplicator_module._default_deduplicator = None

    d1 = get_default_deduplicator()
    d2 = get_default_deduplicator()

    assert isinstance(d1, AlertDeduplicator)
    assert d1 is d2
    assert d1.window_seconds == settings.ALERT_DEDUP_WINDOW_SECONDS
