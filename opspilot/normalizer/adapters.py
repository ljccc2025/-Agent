import threading
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional, Tuple
from opspilot.schemas.task import DiagnosticTask, generate_task_id, TargetType
from opspilot.normalizer.fingerprint import generate_alert_fingerprint


def _extract_target_info(
    data: Dict[str, Any],
    default_target_name: Optional[str] = None,
    default_namespace: Optional[str] = None,
) -> Tuple[TargetType, str, Optional[str]]:
    """从标签或属性字典中提取目标类型、目标名称及命名空间。

    提取优先级：
    1. pod 属性：归类为 k8s_pod，提取 pod 名，提取 namespace（默认 default）。
    2. instance / node / host 属性：归类为 linux_node，自动清理端口，namespace 置 None。
    3. target_type / target_name 显式指定：按显式指定值解析。
    4. 兜底：尝试 job / service / target 或 default_target_name，归类为 k8s_pod。
    """
    # 1. 检查 Pod
    pod = data.get("pod")
    if pod:
        ns = data.get("namespace") or default_namespace or "default"
        return "k8s_pod", str(pod).strip(), str(ns).strip()

    # 2. 检查 Node (instance, node, host)
    node_candidate = data.get("instance") or data.get("node") or data.get("host")
    if node_candidate:
        clean_node = str(node_candidate).split(":")[0].strip()
        return "linux_node", clean_node if clean_node else "unknown-node", None

    # 3. 检查显式 target_type 与 target_name
    if data.get("target_type") in ["k8s_pod", "linux_node"] and data.get("target_name"):
        tt: TargetType = data["target_type"]
        tn = str(data["target_name"]).strip()
        if tt == "linux_node" and ":" in tn:
            tn = tn.split(":")[0].strip()
        ns = data.get("namespace") or (default_namespace if tt == "k8s_pod" else None)
        if tt == "k8s_pod" and not ns:
            ns = "default"
        return tt, tn, ns

    # 4. 兜底
    job = data.get("job") or data.get("service") or data.get("target") or default_target_name
    target_name = str(job).strip() if job else "unknown-service"
    namespace = data.get("namespace") or default_namespace or "default"
    return "k8s_pod", target_name, str(namespace).strip()


class BaseAlertAdapter(ABC):
    """告警适配器抽象基类"""

    @abstractmethod
    def can_handle(self, payload: Dict[str, Any]) -> bool:
        """检查当前适配器是否能够处理该告警载荷格式"""

    @abstractmethod
    def normalize(self, payload: Dict[str, Any], firing_only: bool = True) -> List[DiagnosticTask]:
        """解析并归一化为标准的 DiagnosticTask 列表，每个任务自动计算填充 fingerprint"""


class AlertmanagerAdapter(BaseAlertAdapter):
    """适配标准 Prometheus Alertmanager Webhook JSON"""

    def can_handle(self, payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        if "ruleName" in payload or "evalMatches" in payload:
            return False
        return "alerts" in payload and isinstance(payload.get("alerts"), list)

    def normalize(self, payload: Dict[str, Any], firing_only: bool = True) -> List[DiagnosticTask]:
        if not isinstance(payload, dict):
            return []

        payload_status = str(payload.get("status", "")).lower()
        raw_alerts = payload.get("alerts")
        if isinstance(raw_alerts, list):
            alerts = raw_alerts
        else:
            alerts = [payload]

        tasks: List[DiagnosticTask] = []
        for alert in alerts:
            if not isinstance(alert, dict):
                continue

            alert_status = str(alert.get("status", "")).lower() or payload_status
            if firing_only and alert_status in ["resolved", "ok", "normal"]:
                continue

            labels = alert.get("labels") if isinstance(alert.get("labels"), dict) else {}
            annos = alert.get("annotations") if isinstance(alert.get("annotations"), dict) else {}

            alert_name = str(labels.get("alertname") or labels.get("alert_name") or "UnknownAlert")
            target_type, target_name, namespace = _extract_target_info(labels)

            desc = annos.get("description") or annos.get("summary") or annos.get("message")
            symptoms = str(desc) if desc else f"Alert {alert_name} fired"

            fp = generate_alert_fingerprint(
                alertname=alert_name,
                target_type=target_type,
                target_name=target_name,
                namespace=namespace,
                labels=labels,
            )

            tasks.append(
                DiagnosticTask(
                    task_id=generate_task_id("alert"),
                    source="alertmanager",
                    target_type=target_type,
                    target_name=target_name,
                    namespace=namespace,
                    alert_name=alert_name,
                    alert_labels=labels,
                    symptoms=symptoms,
                    fingerprint=fp,
                )
            )

        return tasks


class GrafanaAlertAdapter(BaseAlertAdapter):
    """适配 Grafana Alerting Webhook（处理 ruleName, state, commonLabels, evalMatches 等）"""

    def can_handle(self, payload: Dict[str, Any]) -> bool:
        if not isinstance(payload, dict):
            return False
        if "ruleName" in payload or "evalMatches" in payload or "ruleId" in payload:
            return True
        if "state" in payload and str(payload.get("state")).lower() in [
            "alerting", "ok", "normal", "resolved", "paused", "pending", "no_data", "execution_error"
        ]:
            return True
        return False

    def normalize(self, payload: Dict[str, Any], firing_only: bool = True) -> List[DiagnosticTask]:
        if not isinstance(payload, dict):
            return []

        state = str(payload.get("state") or "").lower()
        status = str(payload.get("status") or "").lower()

        # Grafana 恢复状态识别过滤
        if firing_only and (state in ["ok", "normal", "resolved"] or status in ["resolved", "ok"]):
            return []

        tasks: List[DiagnosticTask] = []
        common_labels = payload.get("commonLabels") if isinstance(payload.get("commonLabels"), dict) else {}
        rule_name = str(payload.get("ruleName") or payload.get("title") or "GrafanaAlert")
        top_symptoms = payload.get("message") or payload.get("title")

        eval_matches = payload.get("evalMatches")
        alerts = payload.get("alerts")

        if isinstance(eval_matches, list) and len(eval_matches) > 0:
            for match in eval_matches:
                if not isinstance(match, dict):
                    continue

                labels = dict(common_labels)
                tags = match.get("tags") if isinstance(match.get("tags"), dict) else {}
                labels.update(tags)
                if "metric" not in labels and match.get("metric"):
                    labels["metric"] = str(match["metric"])

                alert_name = str(labels.get("alertname") or labels.get("alert_name") or rule_name)
                target_type, target_name, namespace = _extract_target_info(
                    labels, default_target_name=match.get("metric")
                )

                symptoms = str(top_symptoms) if top_symptoms else (
                    f"{alert_name}: {match.get('metric')}={match.get('value')}"
                    if match.get("metric") is not None
                    else f"Alert {alert_name} fired"
                )

                fp = generate_alert_fingerprint(
                    alertname=alert_name,
                    target_type=target_type,
                    target_name=target_name,
                    namespace=namespace,
                    labels=labels,
                )

                tasks.append(
                    DiagnosticTask(
                        task_id=generate_task_id("alert"),
                        source="grafana",
                        target_type=target_type,
                        target_name=target_name,
                        namespace=namespace,
                        alert_name=alert_name,
                        alert_labels=labels,
                        symptoms=symptoms,
                        fingerprint=fp,
                    )
                )

        elif isinstance(alerts, list) and len(alerts) > 0:
            for alert in alerts:
                if not isinstance(alert, dict):
                    continue

                alert_status = str(alert.get("status", "")).lower()
                if firing_only and alert_status in ["resolved", "ok", "normal"]:
                    continue

                labels = dict(common_labels)
                if isinstance(alert.get("labels"), dict):
                    labels.update(alert["labels"])
                annos = alert.get("annotations") if isinstance(alert.get("annotations"), dict) else {}

                alert_name = str(labels.get("alertname") or labels.get("alert_name") or rule_name)
                target_type, target_name, namespace = _extract_target_info(labels)

                desc = annos.get("description") or annos.get("summary") or annos.get("message") or top_symptoms
                symptoms = str(desc) if desc else f"Alert {alert_name} fired"

                fp = generate_alert_fingerprint(
                    alertname=alert_name,
                    target_type=target_type,
                    target_name=target_name,
                    namespace=namespace,
                    labels=labels,
                )

                tasks.append(
                    DiagnosticTask(
                        task_id=generate_task_id("alert"),
                        source="grafana",
                        target_type=target_type,
                        target_name=target_name,
                        namespace=namespace,
                        alert_name=alert_name,
                        alert_labels=labels,
                        symptoms=symptoms,
                        fingerprint=fp,
                    )
                )

        else:
            labels = dict(common_labels)
            if isinstance(payload.get("tags"), dict):
                labels.update(payload["tags"])
            if isinstance(payload.get("labels"), dict):
                labels.update(payload["labels"])

            alert_name = str(labels.get("alertname") or labels.get("alert_name") or rule_name)
            target_type, target_name, namespace = _extract_target_info(labels)
            symptoms = str(top_symptoms) if top_symptoms else f"Alert {alert_name} fired"

            fp = generate_alert_fingerprint(
                alertname=alert_name,
                target_type=target_type,
                target_name=target_name,
                namespace=namespace,
                labels=labels,
            )

            tasks.append(
                DiagnosticTask(
                    task_id=generate_task_id("alert"),
                    source="grafana",
                    target_type=target_type,
                    target_name=target_name,
                    namespace=namespace,
                    alert_name=alert_name,
                    alert_labels=labels,
                    symptoms=symptoms,
                    fingerprint=fp,
                )
            )

        return tasks


class GenericAlertAdapter(BaseAlertAdapter):
    """兜底适配器：处理扁平字典格式的告警"""

    def can_handle(self, payload: Dict[str, Any]) -> bool:
        return isinstance(payload, dict)

    def normalize(self, payload: Dict[str, Any], firing_only: bool = True) -> List[DiagnosticTask]:
        if not isinstance(payload, dict):
            return []

        raw_list = payload.get("alerts") or payload.get("items") or payload.get("events")
        if isinstance(raw_list, list) and raw_list:
            items = raw_list
        else:
            items = [payload]

        tasks: List[DiagnosticTask] = []
        for item in items:
            if not isinstance(item, dict):
                continue

            status = str(
                item.get("status")
                or item.get("state")
                or payload.get("status")
                or payload.get("state")
                or ""
            ).lower()
            if firing_only and status in ["resolved", "ok", "normal"]:
                continue

            if isinstance(item.get("labels"), dict):
                labels = dict(item["labels"])
            elif isinstance(item.get("alert_labels"), dict):
                labels = dict(item["alert_labels"])
            else:
                labels = {k: v for k, v in item.items() if isinstance(v, (str, int, float, bool))}

            alert_name = str(
                item.get("alert_name")
                or item.get("alertname")
                or item.get("name")
                or item.get("title")
                or item.get("ruleName")
                or labels.get("alertname")
                or labels.get("alert_name")
                or "GenericAlert"
            )

            combined_info = {**labels, **item}
            target_type, target_name, namespace = _extract_target_info(combined_info)

            symptoms = str(
                item.get("symptoms")
                or item.get("description")
                or item.get("summary")
                or item.get("message")
                or f"Alert {alert_name} fired"
            )

            fp = generate_alert_fingerprint(
                alertname=alert_name,
                target_type=target_type,
                target_name=target_name,
                namespace=namespace,
                labels=labels,
            )

            tasks.append(
                DiagnosticTask(
                    task_id=generate_task_id("task"),
                    source="generic",
                    target_type=target_type,
                    target_name=target_name,
                    namespace=namespace,
                    alert_name=alert_name,
                    alert_labels=labels,
                    symptoms=symptoms,
                    fingerprint=fp,
                )
            )

        return tasks


class NormalizerRegistry:
    """告警归一化适配器注册中心与格式分发器"""

    def __init__(self):
        self._adapters: List[BaseAlertAdapter] = []
        # 默认内置适配器按优先级注册
        self.register(AlertmanagerAdapter())
        self.register(GrafanaAlertAdapter())
        self.register(GenericAlertAdapter())

    def register(self, adapter: BaseAlertAdapter) -> None:
        self._adapters.append(adapter)

    def normalize(self, raw_payload: Dict[str, Any], firing_only: bool = True) -> List[DiagnosticTask]:
        """自动推断载荷格式并转换为 DiagnosticTask 列表"""
        for adapter in self._adapters:
            if adapter.can_handle(raw_payload):
                return adapter.normalize(raw_payload, firing_only=firing_only)
        return []


_default_normalizer: Optional[NormalizerRegistry] = None
_normalizer_lock = threading.Lock()


def get_default_normalizer() -> NormalizerRegistry:
    """获取全局默认归一化解析器单例"""
    global _default_normalizer
    if _default_normalizer is None:
        with _normalizer_lock:
            if _default_normalizer is None:
                _default_normalizer = NormalizerRegistry()
    return _default_normalizer
