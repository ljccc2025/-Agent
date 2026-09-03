import time
import threading
from typing import Dict, Optional
from pydantic import BaseModel, Field


class DeduplicationResult(BaseModel):
    """告警去重判定结果模型。"""
    is_duplicate: bool
    fingerprint: str
    first_seen: float
    last_seen: float
    duplicate_count: int = Field(default=0, ge=0)


class AlertDeduplicator:
    """基于滑动窗口与 TTL 的线程安全告警防抖去重器。"""

    def __init__(self, window_seconds: int = 300, max_entries: int = 10000):
        self.window_seconds = window_seconds
        self.max_entries = max_entries
        self._cache: Dict[str, DeduplicationResult] = {}
        self._lock = threading.Lock()

    def _purge_expired_unlocked(self, current_time: float) -> int:
        """内部清理已超出 window_seconds 的过期记录（调用方需持有 _lock）。"""
        expired_keys = [
            k for k, v in self._cache.items()
            if current_time - v.last_seen > self.window_seconds
        ]
        for k in expired_keys:
            del self._cache[k]
        return len(expired_keys)

    def _evict_if_needed_unlocked(self, current_time: float) -> None:
        """容量控制：超出 max_entries 时，先淘汰过期条目，不足则淘汰最旧条目（调用方需持有 _lock）。"""
        if len(self._cache) < self.max_entries:
            return

        # 1. 尝试清理所有已过期条目
        self._purge_expired_unlocked(current_time)

        # 2. 若依然达到或超过容量限制，按 last_seen 淘汰最早的记录
        while len(self._cache) >= self.max_entries:
            oldest_key = min(self._cache, key=lambda k: self._cache[k].last_seen)
            del self._cache[oldest_key]

    def process(self, fingerprint: str, timestamp: Optional[float] = None) -> DeduplicationResult:
        """处理并判断告警指纹是否为窗口期内重复告警（线程安全）。

        - 首次遇到：创建新记录，is_duplicate=False, duplicate_count=0。
        - 窗口期内再次遇到：递增 duplicate_count，更新 last_seen，返回 is_duplicate=True。
        - 超出窗口期再次遇到：视为新一轮故障，重置计数与时间，返回 is_duplicate=False。
        """
        now = timestamp if timestamp is not None else time.time()

        with self._lock:
            entry = self._cache.get(fingerprint)

            if entry is not None:
                # 检查是否在滑动窗口内
                if now - entry.last_seen <= self.window_seconds:
                    new_entry = DeduplicationResult(
                        is_duplicate=True,
                        fingerprint=fingerprint,
                        first_seen=entry.first_seen,
                        last_seen=now,
                        duplicate_count=entry.duplicate_count + 1,
                    )
                    self._cache[fingerprint] = new_entry
                    return new_entry
                else:
                    # 超出窗口期，视为新一轮故障
                    new_entry = DeduplicationResult(
                        is_duplicate=False,
                        fingerprint=fingerprint,
                        first_seen=now,
                        last_seen=now,
                        duplicate_count=0,
                    )
                    self._cache[fingerprint] = new_entry
                    return new_entry
            else:
                # 首次遇到该指纹，先进行容量检查
                self._evict_if_needed_unlocked(now)

                new_entry = DeduplicationResult(
                    is_duplicate=False,
                    fingerprint=fingerprint,
                    first_seen=now,
                    last_seen=now,
                    duplicate_count=0,
                )
                self._cache[fingerprint] = new_entry
                return new_entry

    def purge_expired(self, current_time: Optional[float] = None) -> int:
        """清理已超出 window_seconds 的过期记录，返回清理数量。"""
        now = current_time if current_time is not None else time.time()
        with self._lock:
            return self._purge_expired_unlocked(now)

    def clear(self) -> None:
        """清空缓存。"""
        with self._lock:
            self._cache.clear()

    def get_entry(self, fingerprint: str) -> Optional[DeduplicationResult]:
        """获取当前指纹记录状态快照。"""
        with self._lock:
            entry = self._cache.get(fingerprint)
            return entry.model_copy() if entry is not None else None


_default_deduplicator: Optional[AlertDeduplicator] = None
_instance_lock = threading.Lock()


def get_default_deduplicator() -> AlertDeduplicator:
    """获取全局默认去重器单例（结合 settings.ALERT_DEDUP_WINDOW_SECONDS）。"""
    global _default_deduplicator
    if _default_deduplicator is None:
        with _instance_lock:
            if _default_deduplicator is None:
                from opspilot.config import settings
                _default_deduplicator = AlertDeduplicator(
                    window_seconds=settings.ALERT_DEDUP_WINDOW_SECONDS
                )
    return _default_deduplicator
