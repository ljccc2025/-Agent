import hashlib
from typing import Any, Dict, Optional


def generate_alert_fingerprint(
    alertname: str,
    target_type: str,
    target_name: str,
    namespace: Optional[str] = None,
    labels: Optional[Dict[str, Any]] = None,
) -> str:
    """生成确定性 16 位 16 进制 SHA256 告警指纹，具备标签键值排序防抖幂等性。

    规范化逻辑：
    1. alertname, target_type, target_name 规整为 .strip().lower()。
    2. namespace 为空或 None 时标准化为 ""，否则做 .strip().lower()。
    3. labels 按 key 字典序升序排序，剔除空 key 或空值噪声，序列化为 k1=v1;k2=v2 字符串。
    4. Canonical String: f"{alertname}|{target_type}|{target_name}|{namespace}|{canonical_labels}"
    5. 返回 SHA256 摘要的前 16 位小写十六进制字符串。
    """
    clean_alertname = str(alertname).strip().lower()
    clean_target_type = str(target_type).strip().lower()
    clean_target_name = str(target_name).strip().lower()

    if namespace:
        clean_namespace = str(namespace).strip().lower()
    else:
        clean_namespace = ""

    label_parts = []
    if labels:
        for k, v in sorted(labels.items()):
            k_str = str(k).strip()
            if not k_str:
                continue
            if v is None:
                continue
            v_str = str(v).strip()
            if not v_str:
                continue
            label_parts.append(f"{k_str}={v_str}")

    canonical_labels = ";".join(label_parts)
    canonical = (
        f"{clean_alertname}|{clean_target_type}|{clean_target_name}|"
        f"{clean_namespace}|{canonical_labels}"
    )

    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
