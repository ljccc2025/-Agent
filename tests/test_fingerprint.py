import re
import pytest
from opspilot.normalizer.fingerprint import generate_alert_fingerprint
from opspilot.normalizer import generate_alert_fingerprint as generate_alert_fingerprint_pkg


def test_package_export():
    """验证 __init__.py 正确导出了 generate_alert_fingerprint。"""
    assert generate_alert_fingerprint is generate_alert_fingerprint_pkg



def test_fingerprint_deterministic_and_length():
    """验证返回值为 16 位十六进制小写字符串，且确定性幂等。"""
    fp1 = generate_alert_fingerprint(
        alertname="KubePodCrashLooping",
        target_type="k8s_pod",
        target_name="order-api-7b8f9c-xyz",
        namespace="production",
        labels={"severity": "critical", "app": "order-api"}
    )
    fp2 = generate_alert_fingerprint(
        alertname="KubePodCrashLooping",
        target_type="k8s_pod",
        target_name="order-api-7b8f9c-xyz",
        namespace="production",
        labels={"severity": "critical", "app": "order-api"}
    )
    
    assert isinstance(fp1, str)
    assert len(fp1) == 16
    assert re.fullmatch(r"^[0-9a-f]{16}$", fp1) is not None
    assert fp1 == fp2


def test_labels_ordering_idempotence():
    """验证相同内容、不同键序的 labels 输出的指纹 100% 相同。"""
    labels_a = {
        "cluster": "k8s-prod-sh",
        "env": "production",
        "app": "order-service",
        "tier": "backend",
        "region": "cn-east-1"
    }
    labels_b = {
        "region": "cn-east-1",
        "tier": "backend",
        "app": "order-service",
        "cluster": "k8s-prod-sh",
        "env": "production"
    }
    
    fp_a = generate_alert_fingerprint(
        alertname="HighMemoryUsage",
        target_type="k8s_pod",
        target_name="order-service-001",
        namespace="prod",
        labels=labels_a
    )
    fp_b = generate_alert_fingerprint(
        alertname="HighMemoryUsage",
        target_type="k8s_pod",
        target_name="order-service-001",
        namespace="prod",
        labels=labels_b
    )
    assert fp_a == fp_b


def test_different_targets_produce_different_fingerprints():
    """验证不同 pod 名称指纹互斥。"""
    fp1 = generate_alert_fingerprint(
        alertname="KubePodCrashLooping",
        target_type="k8s_pod",
        target_name="order-api-pod-1",
        namespace="prod"
    )
    fp2 = generate_alert_fingerprint(
        alertname="KubePodCrashLooping",
        target_type="k8s_pod",
        target_name="order-api-pod-2",
        namespace="prod"
    )
    assert fp1 != fp2


def test_different_namespaces_produce_different_fingerprints():
    """验证相同 Pod 名在不同 namespace（如 prod vs dev）指纹互斥。"""
    fp_prod = generate_alert_fingerprint(
        alertname="KubePodCrashLooping",
        target_type="k8s_pod",
        target_name="payment-svc-xyz",
        namespace="prod"
    )
    fp_dev = generate_alert_fingerprint(
        alertname="KubePodCrashLooping",
        target_type="k8s_pod",
        target_name="payment-svc-xyz",
        namespace="dev"
    )
    assert fp_prod != fp_dev


def test_different_target_types_produce_different_fingerprints():
    """验证 k8s_pod 与 linux_node 指纹互斥。"""
    fp_k8s = generate_alert_fingerprint(
        alertname="NodeDiskPressure",
        target_type="k8s_pod",
        target_name="node-exporter",
        namespace="infra"
    )
    fp_node = generate_alert_fingerprint(
        alertname="NodeDiskPressure",
        target_type="linux_node",
        target_name="node-exporter",
        namespace="infra"
    )
    assert fp_k8s != fp_node


def test_empty_and_none_labels_handling():
    """验证 None 或空字典平稳处理且结果一致。"""
    fp_none = generate_alert_fingerprint(
        alertname="HighCpuLoad",
        target_type="linux_node",
        target_name="192.168.1.100",
        namespace=None,
        labels=None
    )
    fp_empty = generate_alert_fingerprint(
        alertname="HighCpuLoad",
        target_type="linux_node",
        target_name="192.168.1.100",
        namespace="",
        labels={}
    )
    assert fp_none == fp_empty
    assert len(fp_none) == 16


def test_case_insensitivity_normalization():
    """验证大小写与空白字符归一化后产生相同指纹。"""
    fp_upper = generate_alert_fingerprint(
        alertname="  KubePodCrashLooping  ",
        target_type="  K8S_POD  ",
        target_name="  Order-Api-XYZ  ",
        namespace="  PRODUCTION  ",
        labels={"ENV": "PROD", "APP": "ORDER"}
    )
    fp_lower = generate_alert_fingerprint(
        alertname="kubepodcrashlooping",
        target_type="k8s_pod",
        target_name="order-api-xyz",
        namespace="production",
        labels={"ENV": "PROD", "APP": "ORDER"}
    )
    assert fp_upper == fp_lower


def test_labels_noise_filtering():
    """验证 labels 中空值与 None 噪声能够被剔除，与纯净 labels 保持一致。"""
    fp_with_noise = generate_alert_fingerprint(
        alertname="DiskFull",
        target_type="linux_node",
        target_name="node-1",
        labels={"app": "db", "cluster": "", "team": None, "  ": "invalid", "tier": "  "}
    )
    fp_clean = generate_alert_fingerprint(
        alertname="DiskFull",
        target_type="linux_node",
        target_name="node-1",
        labels={"app": "db"}
    )
    assert fp_with_noise == fp_clean
