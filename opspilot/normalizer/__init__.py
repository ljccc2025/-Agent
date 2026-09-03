"""OpsPilot Normalizer package."""

from opspilot.normalizer.fingerprint import generate_alert_fingerprint
from opspilot.normalizer.deduplicator import (
    AlertDeduplicator,
    DeduplicationResult,
    get_default_deduplicator,
)
from opspilot.normalizer.throttler import (
    AlertStormThrottler,
    StormThrottleResult,
    get_default_throttler,
)
from opspilot.normalizer.adapters import (
    BaseAlertAdapter,
    AlertmanagerAdapter,
    GrafanaAlertAdapter,
    GenericAlertAdapter,
    NormalizerRegistry,
    get_default_normalizer,
)

__all__ = [
    "generate_alert_fingerprint",
    "AlertDeduplicator",
    "DeduplicationResult",
    "get_default_deduplicator",
    "AlertStormThrottler",
    "StormThrottleResult",
    "get_default_throttler",
    "BaseAlertAdapter",
    "AlertmanagerAdapter",
    "GrafanaAlertAdapter",
    "GenericAlertAdapter",
    "NormalizerRegistry",
    "get_default_normalizer",
]
