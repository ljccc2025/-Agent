"""OpsPilot Normalizer package."""

from opspilot.normalizer.fingerprint import generate_alert_fingerprint
from opspilot.normalizer.deduplicator import (
    AlertDeduplicator,
    DeduplicationResult,
    get_default_deduplicator,
)

__all__ = [
    "generate_alert_fingerprint",
    "AlertDeduplicator",
    "DeduplicationResult",
    "get_default_deduplicator",
]
