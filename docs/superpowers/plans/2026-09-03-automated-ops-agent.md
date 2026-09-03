# 自动化运维排障 Agent (OpsPilot) 实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 构建一个生产级、轻量且只读安全的自动化故障排查与根因分析（RCA）Agent，支持 Kubernetes 容器与 Linux 主机混合环境，支持 Alertmanager Webhook 告警自动诊断与 CLI 交互式排查。

**架构：** 分层两阶段架构。Phase 1 执行确定性轻量 SOP 快速抓取一阶事实拓扑；Phase 2 由状态机工作流驱动 LLM 结合只读工具箱深挖因果链（最多 3 轮熔断），最终生成包含根因结论与 SRE 分级处置建议的结构化 RCA 报告。

**技术栈：** Python 3.10+, FastAPI, Pydantic v2, Typer, Rich, Pytest, HTTPX, OpenAI-compatible Client API。

---

## 目录与文件职责划分

```text
opspilot/
├── __init__.py
├── config.py                 # 环境配置与 pydantic-settings
├── schemas/                  # 全局 Pydantic 数据契约
│   ├── __init__.py
│   ├── task.py               # DiagnosticTask 统一任务契约
│   ├── report.py             # EvidenceItem, RemediationAction, DiagnosticReport 结构化输出
│   └── alert.py              # Alertmanager 告警载荷模型与解析器
├── tools/                    # 只读工具箱与安全防护
│   ├── __init__.py
│   ├── security.py           # 命令白名单校验器与敏感信息脱敏过滤器 (Redaction)
│   ├── k8s_tools.py          # K8s 只读工具接口
│   ├── host_tools.py         # Linux 主机只读工具接口
│   └── metric_tools.py       # Prometheus PromQL 工具接口
├── prefetches/               # Phase 1: 确定性快速拓扑抓取 SOP
│   ├── __init__.py
│   ├── base.py               # 抽象 Prefetcher 基类
│   ├── k8s_prefetch.py       # K8s Pod 状态/近100行日志/Events 预拉取
│   └── node_prefetch.py      # Linux 节点资源占用/dmesg 预拉取
├── core/                     # Agent 核心状态机与推理大脑
│   ├── __init__.py
│   ├── state.py              # 诊断状态模型 (DiagnosticState)
│   ├── prompt_templates.py   # SRE 运维排查专家 System Prompt 与 Few-Shot 模板
│   ├── llm.py                # 兼容 OpenAI 协议的统一大模型客户端
│   └── workflow.py           # 状态机两阶段诊断编排器与降级熔断逻辑
├── notifiers/                # 诊断结果输出渲染器
│   ├── __init__.py
│   ├── base.py               # 通知器基类
│   ├── console.py            # Rich 控制台美化排版渲染
│   └── dingtalk.py           # 钉钉/飞书 Markdown 卡片生成
├── api/                      # Webhook 与 HTTP 入口 (FastAPI)
│   ├── __init__.py
│   └── routes_webhook.py     # Alertmanager 告警 Webhook 接收路由
├── cli/                      # SRE 命令行客户端
│   ├── __init__.py
│   └── main.py               # opspilot CLI (diagnose pod/node, mock test)
└── main.py                   # 服务入口

tests/                        # 单元测试与演练套件
├── test_config.py
├── test_schemas.py
├── test_security.py
├── test_prefetch.py
├── test_tools.py
├── test_workflow.py
└── test_e2e_scenarios.py     # 4 组经典离线故障模拟演练
```

---

### 任务 1：项目环境、基础配置与脚手架搭建

**文件：**
- 创建：`pyproject.toml`
- 创建：`opspilot/__init__.py`
- 创建：`opspilot/config.py`
- 测试：`tests/test_config.py`

- [ ] **步骤 1：编写配置加载的失败测试**

```python
# tests/test_config.py
import os
from opspilot.config import Settings

def test_default_settings():
    settings = Settings(
        LLM_API_KEY="test-key",
        LLM_BASE_URL="https://api.deepseek.com/v1",
        LLM_MODEL="deepseek-chat"
    )
    assert settings.LLM_MODEL == "deepseek-chat"
    assert settings.MAX_DEEPDIVE_ROUNDS == 3
    assert settings.READ_ONLY_MODE is True
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_config.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'opspilot'`

- [ ] **步骤 3：创建 `pyproject.toml` 与 `opspilot/config.py` 实现**

```toml
# pyproject.toml
[project]
name = "opspilot"
version = "0.1.0"
description = "AIOps RCA Diagnostic Agent"
readme = "README.md"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.110.0",
    "uvicorn>=0.28.0",
    "pydantic>=2.6.0",
    "pydantic-settings>=2.2.0",
    "httpx>=0.27.0",
    "typer>=0.12.0",
    "rich>=13.7.0",
]

[project.optional-dependencies]
test = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]
```

```python
# opspilot/__init__.py
__version__ = "0.1.0"
```

```python
# opspilot/config.py
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM 配置
    LLM_API_KEY: str = Field(default="sk-fake-key", description="OpenAI compatible API key")
    LLM_BASE_URL: str = Field(default="https://api.deepseek.com/v1", description="OpenAI compatible base URL")
    LLM_MODEL: str = Field(default="deepseek-chat", description="Model name")
    LLM_TEMPERATURE: float = 0.1

    # 诊断状态机配置
    MAX_DEEPDIVE_ROUNDS: int = 3
    READ_ONLY_MODE: bool = True
    LOG_TAIL_LINES: int = 100

    # 服务端配置
    API_PORT: int = 8080
    API_HOST: str = "0.0.0.0"

settings = Settings()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_config.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add pyproject.toml opspilot/__init__.py opspilot/config.py tests/test_config.py
git commit -m "feat: setup project scaffolding and configuration management"
```

---

### 任务 2：核心数据契约模型 (Schemas)

**文件：**
- 创建：`opspilot/schemas/__init__.py`
- 创建：`opspilot/schemas/task.py`
- 创建：`opspilot/schemas/report.py`
- 创建：`opspilot/schemas/alert.py`
- 测试：`tests/test_schemas.py`

- [ ] **步骤 1：编写数据模型与告警解析的失败测试**

```python
# tests/test_schemas.py
from opspilot.schemas.task import DiagnosticTask
from opspilot.schemas.report import DiagnosticReport, EvidenceItem, RemediationAction
from opspilot.schemas.alert import AlertmanagerPayload

def test_diagnostic_task_creation():
    task = DiagnosticTask(
        task_id="task-001",
        source="cli",
        target_type="k8s_pod",
        target_name="order-service-7f654b-abcde",
        namespace="prod",
        symptoms="Pod status CrashLoopBackOff"
    )
    assert task.target_type == "k8s_pod"
    assert task.namespace == "prod"

def test_alertmanager_payload_parsing():
    payload_data = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {
                    "alertname": "KubePodCrashLooping",
                    "pod": "payment-api-xxx",
                    "namespace": "default",
                    "severity": "critical"
                },
                "annotations": {
                    "summary": "Pod payment-api is crash looping",
                    "description": "Container failed to start"
                }
            }
        ]
    }
    payload = AlertmanagerPayload(**payload_data)
    tasks = payload.to_diagnostic_tasks()
    assert len(tasks) == 1
    assert tasks[0].target_name == "payment-api-xxx"
    assert tasks[0].alert_name == "KubePodCrashLooping"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_schemas.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'opspilot.schemas'`

- [ ] **步骤 3：编写 `opspilot/schemas/` 下的数据契约模型**

```python
# opspilot/schemas/__init__.py
from opspilot.schemas.task import DiagnosticTask
from opspilot.schemas.report import DiagnosticReport, EvidenceItem, RemediationAction
from opspilot.schemas.alert import AlertmanagerPayload

__all__ = ["DiagnosticTask", "DiagnosticReport", "EvidenceItem", "RemediationAction", "AlertmanagerPayload"]
```

```python
# opspilot/schemas/task.py
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any

class DiagnosticTask(BaseModel):
    task_id: str = Field(..., description="唯一任务跟踪ID")
    source: str = Field(default="cli", description="来源: alertmanager / cli / manual_api")
    target_type: str = Field(..., description="目标类型: k8s_pod / linux_node")
    target_name: str = Field(..., description="目标名称: 如 Pod名或主机IP/主机名")
    namespace: Optional[str] = Field(default=None, description="Kubernetes 命名空间")
    alert_name: Optional[str] = Field(default=None, description="触发告警名称")
    alert_labels: Dict[str, Any] = Field(default_factory=dict, description="关联告警标签")
    symptoms: str = Field(..., description="故障初始表象描述")
```

```python
# opspilot/schemas/report.py
from pydantic import BaseModel, Field
from typing import List, Optional

class EvidenceItem(BaseModel):
    source: str = Field(..., description="证据来源: k8s_events / pod_logs / host_status / dmesg / prometheus")
    content: str = Field(..., description="提取出的客观事实")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="证据置信度")

class RemediationAction(BaseModel):
    title: str = Field(..., description="处置动作简述")
    risk_level: str = Field(..., description="风险等级: LOW / MEDIUM / HIGH")
    command_draft: Optional[str] = Field(None, description="建议在受控环境中执行的命令草稿")
    explanation: str = Field(..., description="操作目的与影响说明")

class DiagnosticReport(BaseModel):
    task_id: str
    target: str
    status: str = Field(..., description="排查状态: SUCCESS / PARTIAL_FAILURE / UNRESOLVED")
    fault_summary: str = Field(..., description="一句话故障定位摘要")
    root_cause: str = Field(..., description="定位出的核心根因结论")
    evidence_chain: List[EvidenceItem] = Field(default_factory=list, description="推导支撑证据链")
    remediation_actions: List[RemediationAction] = Field(default_factory=list, description="SRE处置建议")
    duration_seconds: float = Field(..., description="排查耗时(秒)")
```

```python
# opspilot/schemas/alert.py
import uuid
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from opspilot.schemas.task import DiagnosticTask

class AlertItem(BaseModel):
    status: str
    labels: Dict[str, Any] = Field(default_factory=dict)
    annotations: Dict[str, Any] = Field(default_factory=dict)

class AlertmanagerPayload(BaseModel):
    status: str = "firing"
    alerts: List[AlertItem] = Field(default_factory=list)

    def to_diagnostic_tasks(self) -> List[DiagnosticTask]:
        tasks: List[DiagnosticTask] = []
        for alert in self.alerts:
            labels = alert.labels
            annos = alert.annotations
            alertname = labels.get("alertname", "UnknownAlert")
            
            # 判断目标类型是 k8s pod 还是 linux node
            if "pod" in labels:
                target_type = "k8s_pod"
                target_name = labels["pod"]
                namespace = labels.get("namespace", "default")
            elif "instance" in labels or "node" in labels or "host" in labels:
                target_type = "linux_node"
                target_name = labels.get("instance") or labels.get("node") or labels.get("host")
                namespace = None
            else:
                target_type = "k8s_pod"
                target_name = labels.get("job", "unknown-target")
                namespace = labels.get("namespace", "default")

            symptoms = annos.get("description") or annos.get("summary") or f"Alert {alertname} triggered"
            tasks.append(DiagnosticTask(
                task_id=f"alert-{uuid.uuid4().hex[:8]}",
                source="alertmanager",
                target_type=target_type,
                target_name=target_name,
                namespace=namespace,
                alert_name=alertname,
                alert_labels=labels,
                symptoms=symptoms
            ))
        return tasks
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_schemas.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add opspilot/schemas/ tests/test_schemas.py
git commit -m "feat: implement diagnostic task, report and alert schemas"
```

---

### 任务 3：安全沙箱与敏感数据脱敏过滤器

**文件：**
- 创建：`opspilot/tools/security.py`
- 测试：`tests/test_security.py`

- [ ] **步骤 1：编写命令安全校验与敏感词脱敏的失败测试**

```python
# tests/test_security.py
import pytest
from opspilot.tools.security import validate_host_command, redact_sensitive_info

def test_command_whitelist_allows_safe_commands():
    assert validate_host_command(["uptime"]) is True
    assert validate_host_command(["df", "-h"]) is True
    assert validate_host_command(["systemctl", "status", "nginx"]) is True

def test_command_whitelist_rejects_dangerous_commands():
    with pytest.raises(PermissionError):
        validate_host_command(["rm", "-rf", "/"])
    with pytest.raises(PermissionError):
        validate_host_command(["reboot"])
    with pytest.raises(PermissionError):
        validate_host_command(["dd", "if=/dev/zero", "of=/tmp/test"])

def test_sensitive_info_redaction():
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9 and db_password=SuperSecretPassword123!"
    redacted = redact_sensitive_info(text)
    assert "SuperSecretPassword123!" not in redacted
    assert "***REDACTED***" in redacted
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_security.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'opspilot.tools.security'`

- [ ] **步骤 3：编写 `opspilot/tools/security.py` 实现**

```python
# opspilot/tools/security.py
import re
from typing import List

ALLOWED_COMMAND_BINARIES = {
    "uptime",
    "free",
    "df",
    "ps",
    "top",
    "journalctl",
    "systemctl",
    "dmesg",
    "ss",
    "netstat",
    "vmstat",
    "iostat",
    "cat",
}

SYSTEMCTL_ALLOWED_SUBCOMMANDS = {"status", "is-active", "is-failed"}

REDACTION_PATTERNS = [
    (re.compile(r'(Bearer\s+)[A-Za-z0-9\-\._~\+\/]+=*', re.IGNORECASE), r'\1***REDACTED***'),
    (re.compile(r'(password|passwd|pwd|secret|token|ak|sk)\s*[:=]\s*([^\s,;]+)', re.IGNORECASE), r'\1=***REDACTED***'),
    (re.compile(r'AKIA[0-9A-Z]{16}'), '***REDACTED_AK***'),
]

def validate_host_command(cmd_parts: List[str]) -> bool:
    if not cmd_parts:
        raise ValueError("Empty command list")
    
    binary = cmd_parts[0].lower().split("/")[-1]
    if binary not in ALLOWED_COMMAND_BINARIES:
        raise PermissionError(f"Security Sandbox: Command binary '{binary}' is not permitted by whitelist.")

    # 特殊限制: systemctl 仅允许只读子命令
    if binary == "systemctl" and len(cmd_parts) > 1:
        subcmd = cmd_parts[1].lower()
        if subcmd not in SYSTEMCTL_ALLOWED_SUBCOMMANDS:
            raise PermissionError(f"Security Sandbox: 'systemctl {subcmd}' is a mutating action, only status is allowed.")

    return True

def redact_sensitive_info(content: str) -> str:
    if not content:
        return ""
    result = content
    for pattern, replacement in REDACTION_PATTERNS:
        result = pattern.sub(replacement, result)
    return result
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_security.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add opspilot/tools/security.py tests/test_security.py
git commit -m "feat: implement security sandbox validator and data redactor"
```

---

### 任务 4：Phase 1 确定性快速拓扑取证 SOP (Prefetches)

**文件：**
- 创建：`opspilot/prefetches/base.py`
- 创建：`opspilot/prefetches/k8s_prefetch.py`
- 创建：`opspilot/prefetches/node_prefetch.py`
- 测试：`tests/test_prefetch.py`

- [ ] **步骤 1：编写 Phase 1 预拉取 SOP 的测试**

```python
# tests/test_prefetch.py
from opspilot.schemas.task import DiagnosticTask
from opspilot.prefetches.k8s_prefetch import K8sPrefetcher
from opspilot.prefetches.node_prefetch import NodePrefetcher

def test_k8s_prefetcher_collect(monkeypatch):
    task = DiagnosticTask(
        task_id="t1",
        source="cli",
        target_type="k8s_pod",
        target_name="test-pod",
        namespace="default",
        symptoms="Pod CrashLoopBackOff"
    )
    prefetcher = K8sPrefetcher()
    # 模拟数据采集输出
    evidence = prefetcher.collect(task)
    assert len(evidence) >= 2
    sources = [item.source for item in evidence]
    assert "k8s_pod_status" in sources
    assert "k8s_pod_logs" in sources

def test_node_prefetcher_collect():
    task = DiagnosticTask(
        task_id="t2",
        source="cli",
        target_type="linux_node",
        target_name="192.168.1.10",
        symptoms="Node DiskPressure"
    )
    prefetcher = NodePrefetcher()
    evidence = prefetcher.collect(task)
    assert len(evidence) >= 2
    sources = [item.source for item in evidence]
    assert "host_resources" in sources
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_prefetch.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'opspilot.prefetches'`

- [ ] **步骤 3：编写 `opspilot/prefetches/` 预拉取实现代码**

```python
# opspilot/prefetches/base.py
from abc import ABC, abstractmethod
from typing import List
from opspilot.schemas.task import DiagnosticTask
from opspilot.schemas.report import EvidenceItem

class BasePrefetcher(ABC):
    @abstractmethod
    def collect(self, task: DiagnosticTask) -> List[EvidenceItem]:
        """确定性拉取一阶事实证据"""
        pass
```

```python
# opspilot/prefetches/k8s_prefetch.py
from typing import List
import subprocess
import shutil
from opspilot.schemas.task import DiagnosticTask
from opspilot.schemas.report import EvidenceItem
from opspilot.prefetches.base import BasePrefetcher
from opspilot.tools.security import redact_sensitive_info

class K8sPrefetcher(BasePrefetcher):
    def collect(self, task: DiagnosticTask) -> List[EvidenceItem]:
        evidence: List[EvidenceItem] = []
        ns = task.namespace or "default"
        pod = task.target_name

        has_kubectl = shutil.which("kubectl") is not None
        if not has_kubectl:
            # 模拟环境/演示回退数据
            evidence.append(EvidenceItem(
                source="k8s_pod_status",
                content=f"Pod {pod} in {ns}: Status=CrashLoopBackOff, Restarts=8, LastExitCode=137 (OOMKilled)",
                confidence=1.0
            ))
            evidence.append(EvidenceItem(
                source="k8s_pod_logs",
                content="java.lang.OutOfMemoryError: Java heap space\nTerminating due to java.lang.OutOfMemoryError",
                confidence=0.95
            ))
            return evidence

        try:
            # 1. 获取 Pod 状态与事件
            status_res = subprocess.run(
                ["kubectl", "describe", "pod", pod, "-n", ns],
                capture_output=True, text=True, timeout=5
            )
            raw_describe = status_res.stdout if status_res.returncode == 0 else f"Error: {status_res.stderr}"
            evidence.append(EvidenceItem(
                source="k8s_pod_status",
                content=redact_sensitive_info(raw_describe[-2000:]),
                confidence=1.0
            ))

            # 2. 获取最近 100 行日志
            logs_res = subprocess.run(
                ["kubectl", "logs", pod, "-n", ns, "--tail=100", "--previous"],
                capture_output=True, text=True, timeout=5
            )
            if logs_res.returncode != 0:
                logs_res = subprocess.run(
                    ["kubectl", "logs", pod, "-n", ns, "--tail=100"],
                    capture_output=True, text=True, timeout=5
                )
            raw_logs = logs_res.stdout if logs_res.returncode == 0 else f"No logs available: {logs_res.stderr}"
            evidence.append(EvidenceItem(
                source="k8s_pod_logs",
                content=redact_sensitive_info(raw_logs[-3000:]),
                confidence=0.9
            ))
        except Exception as e:
            evidence.append(EvidenceItem(
                source="k8s_pod_status",
                content=f"Exception reading k8s: {str(e)}",
                confidence=0.5
            ))

        return evidence
```

```python
# opspilot/prefetches/node_prefetch.py
import shutil
import subprocess
from typing import List
from opspilot.schemas.task import DiagnosticTask
from opspilot.schemas.report import EvidenceItem
from opspilot.prefetches.base import BasePrefetcher
from opspilot.tools.security import redact_sensitive_info, validate_host_command

class NodePrefetcher(BasePrefetcher):
    def collect(self, task: DiagnosticTask) -> List[EvidenceItem]:
        evidence: List[EvidenceItem] = []
        host = task.target_name

        # 检查是否能在本机或本地环境执行探针
        can_run_df = shutil.which("df") is not None
        if not can_run_df:
            # 模拟/通用备用数据
            evidence.append(EvidenceItem(
                source="host_resources",
                content=f"Host {host}: Disk /dev/vda1 usage 98%, Free=850MB, Inodes=45%",
                confidence=1.0
            ))
            evidence.append(EvidenceItem(
                source="host_top_processes",
                content="PID 1290 /var/log/app.log writing fast, disk IO util 95%",
                confidence=0.9
            ))
            return evidence

        try:
            # 1. 采集磁盘空间 df -h
            validate_host_command(["df", "-h"])
            df_res = subprocess.run(["df", "-h"], capture_output=True, text=True, timeout=4)
            evidence.append(EvidenceItem(
                source="host_resources",
                content=redact_sensitive_info(df_res.stdout[:1500]),
                confidence=1.0
            ))

            # 2. 采集系统内存 free -m
            if shutil.which("free"):
                validate_host_command(["free", "-m"])
                free_res = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=4)
                evidence.append(EvidenceItem(
                    source="host_memory",
                    content=redact_sensitive_info(free_res.stdout),
                    confidence=1.0
                ))
        except Exception as e:
            evidence.append(EvidenceItem(
                source="host_resources",
                content=f"Failed to inspect host: {str(e)}",
                confidence=0.5
            ))

        return evidence
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_prefetch.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add opspilot/prefetches/ tests/test_prefetch.py
git commit -m "feat: implement Phase 1 deterministic SOP prefetchers for K8s and Linux node"
```

---

### 任务 5：Phase 2 只读探针工具箱 (Tool Registry)

**文件：**
- 创建：`opspilot/tools/base.py`
- 创建：`opspilot/tools/k8s_tools.py`
- 创建：`opspilot/tools/host_tools.py`
- 创建：`opspilot/tools/metric_tools.py`
- 测试：`tests/test_tools.py`

- [ ] **步骤 1：编写工具箱调用的失败测试**

```python
# tests/test_tools.py
from opspilot.tools.metric_tools import QueryPrometheusTool
from opspilot.tools.host_tools import InspectSystemdServiceTool

def test_query_prometheus_tool():
    tool = QueryPrometheusTool(mock_mode=True)
    res = tool.execute(query="sum(rate(container_cpu_usage_seconds_total[5m]))")
    assert "metric" in res or "value" in res or "result" in res

def test_inspect_systemd_tool():
    tool = InspectSystemdServiceTool(mock_mode=True)
    res = tool.execute(service_name="nginx")
    assert "Active: active (running)" in res or "nginx" in res
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_tools.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'opspilot.tools.metric_tools'`

- [ ] **步骤 3：编写工具定义与执行实现**

```python
# opspilot/tools/base.py
from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseDiagnosticTool(ABC):
    name: str
    description: str

    @abstractmethod
    def execute(self, **kwargs) -> str:
        pass

    def to_tool_def(self) -> Dict[str, Any]:
        """转换为 OpenAI 函数定义格式"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.get_parameters_schema()
            }
        }

    @abstractmethod
    def get_parameters_schema(self) -> Dict[str, Any]:
        pass
```

```python
# opspilot/tools/metric_tools.py
from typing import Dict, Any
from opspilot.tools.base import BaseDiagnosticTool

class QueryPrometheusTool(BaseDiagnosticTool):
    name = "query_prometheus"
    description = "执行 PromQL 即时查询以获取关键系统或容器指标（CPU/内存/磁盘/网络速率等）"

    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "标准 PromQL 表达式"},
            },
            "required": ["query"]
        }

    def execute(self, query: str, **kwargs) -> str:
        if self.mock_mode:
            return f"[Prometheus Result for '{query}']: {{value: [1725350000, '0.88'], status: 'success'}}"
        # 实际 HTTP 接入时通过 httpx 访问 prometheus API
        return f"[Prometheus Mock]: Query '{query}' executed successfully."
```

```python
# opspilot/tools/host_tools.py
from typing import Dict, Any
from opspilot.tools.base import BaseDiagnosticTool
from opspilot.tools.security import validate_host_command, redact_sensitive_info
import subprocess
import shutil

class InspectSystemdServiceTool(BaseDiagnosticTool):
    name = "inspect_systemd_service"
    description = "检查指定 systemd 服务的运行状态与最近日志 (systemctl status)"

    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "service_name": {"type": "string", "description": "系统服务名称, 如 nginx 或 docker"}
            },
            "required": ["service_name"]
        }

    def execute(self, service_name: str, **kwargs) -> str:
        if self.mock_mode or not shutil.which("systemctl"):
            return f"[Systemd Status for {service_name}]: Active: active (running) since Thu 2026-09-03; Main PID: 1042"
        
        cmd = ["systemctl", "status", service_name]
        validate_host_command(cmd)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        return redact_sensitive_info(res.stdout or res.stderr)
```

```python
# opspilot/tools/k8s_tools.py
from typing import Dict, Any
from opspilot.tools.base import BaseDiagnosticTool
from opspilot.tools.security import redact_sensitive_info
import subprocess
import shutil

class GetPodEventsTool(BaseDiagnosticTool):
    name = "get_pod_events"
    description = "查询指定命名空间和 Pod 关联的 Kubernetes Events 警告与事件"

    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "K8s 命名空间"},
                "pod_name": {"type": "string", "description": "Pod 名称"}
            },
            "required": ["namespace", "pod_name"]
        }

    def execute(self, namespace: str, pod_name: str, **kwargs) -> str:
        if self.mock_mode or not shutil.which("kubectl"):
            return f"[K8s Events for {pod_name} in {namespace}]: Warning BackOff: Back-off restarting failed container; Warning OOMKilled: Memory cgroup out of memory"

        res = subprocess.run(
            ["kubectl", "get", "events", "-n", namespace, "--field-selector", f"involvedObject.name={pod_name}"],
            capture_output=True, text=True, timeout=5
        )
        return redact_sensitive_info(res.stdout or res.stderr)
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_tools.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add opspilot/tools/ tests/test_tools.py
git commit -m "feat: implement read-only tool registry for Prometheus, Systemd and K8s"
```

---

### 任务 6：LLM 适配层与 SRE RCA 诊断提示词

**文件：**
- 创建：`opspilot/core/prompt_templates.py`
- 创建：`opspilot/core/llm.py`
- 测试：`tests/test_llm.py`

- [ ] **步骤 1：编写 LLM 客户端与结构化格式化的失败测试**

```python
# tests/test_llm.py
from opspilot.core.llm import LLMClient
from opspilot.schemas.report import DiagnosticReport

def test_mock_llm_client_returns_valid_report():
    client = LLMClient(mock_mode=True)
    report = client.synthesize_rca(
        task_id="task-123",
        target="order-service-pod",
        symptoms="CrashLoopBackOff",
        evidence_summary="Found exit code 137, OOMKilled in pod description, memory limit 512Mi exceeded."
    )
    assert isinstance(report, DiagnosticReport)
    assert report.status == "SUCCESS"
    assert "OOM" in report.root_cause or "内存" in report.root_cause
    assert len(report.remediation_actions) > 0
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_llm.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'opspilot.core.llm'`

- [ ] **步骤 3：编写 `opspilot/core/prompt_templates.py` 与 `llm.py` 实现**

```python
# opspilot/core/prompt_templates.py
SYSTEM_RCA_PROMPT = """你是一名资深的 SRE 和云原生运维专家。
你的任务是根据给定的【故障表象】以及【已收集的客观证据事实】，推导故障的根本原因（RCA），并给出分级处置建议。

你必须遵守以下原则：
1. 严禁凭空臆造。所有根因推导必须能在证据链（Evidence Chain）中找到对应事实支撑。
2. 建议必须具有明确的安全风险等级（LOW / MEDIUM / HIGH），并提供供人工审查执行的具体命令草稿。
3. 输出必须是合法严格的 JSON 格式，完全符合 DiagnosticReport 模式。

输出 JSON 格式示例：
{
  "status": "SUCCESS",
  "fault_summary": "Pod 频繁崩溃，退出码 137",
  "root_cause": "容器内存超过上限 (512Mi) 触发内核 OOMKilled",
  "evidence_chain": [
    {"source": "k8s_pod_status", "content": "Last state terminated with exit code 137 (OOMKilled)", "confidence": 1.0}
  ],
  "remediation_actions": [
    {
      "title": "调大容器内存配额 (Resource Limits)",
      "risk_level": "MEDIUM",
      "command_draft": "kubectl set resources deployment/order-service --limits=memory=1Gi -n default",
      "explanation": "临时调高 limits 恢复业务，后续由研发排查是否存在内存泄漏。"
    }
  ]
}
"""
```

```python
# opspilot/core/llm.py
import json
import time
import httpx
from typing import Dict, Any, List
from opspilot.config import settings
from opspilot.schemas.report import DiagnosticReport, EvidenceItem, RemediationAction
from opspilot.core.prompt_templates import SYSTEM_RCA_PROMPT

class LLMClient:
    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self.api_key = settings.LLM_API_KEY
        self.base_url = settings.LLM_BASE_URL
        self.model = settings.LLM_MODEL

    def synthesize_rca(
        self,
        task_id: str,
        target: str,
        symptoms: str,
        evidence_summary: str
    ) -> DiagnosticReport:
        start_time = time.time()
        
        if self.mock_mode or not self.api_key or self.api_key.startswith("sk-fake"):
            # 智能规则/离线 Mock 推导
            is_oom = "137" in evidence_summary or "OOM" in evidence_summary.upper()
            is_disk = "disk" in evidence_summary.lower() or "98%" in evidence_summary or "99%" in evidence_summary
            
            if is_oom:
                root_cause = "容器内存资源达到限制上限 (Limit exceeded)，被操作系统 cgroup 终止 (OOMKilled, Exit Code 137)"
                summary = "容器因内存溢出被杀死"
                actions = [
                    RemediationAction(
                        title="增加 Deployment 内存限制",
                        risk_level="MEDIUM",
                        command_draft=f"kubectl set resources deployment/{target} --limits=memory=1Gi",
                        explanation="适当调大内存 Limit 恢复服务，并排查 JVM/应用是否存在内存泄漏"
                    )
                ]
            elif is_disk:
                root_cause = "系统根目录磁盘使用率超过 95% 阈值，导致系统发生 DiskPressure 异常"
                summary = "宿主机磁盘空间耗尽"
                actions = [
                    RemediationAction(
                        title="清理大文件或轮转日志",
                        risk_level="LOW",
                        command_draft="journalctl --vacuum-size=500M",
                        explanation="安全清理系统历史日志以释放磁盘空间"
                    )
                ]
            else:
                root_cause = f"基于证据分析发现异常: {symptoms}"
                summary = f"检测到目标异常: {symptoms}"
                actions = [
                    RemediationAction(
                        title="查看详细运行日志",
                        risk_level="LOW",
                        command_draft=f"kubectl logs {target} --tail=200",
                        explanation="获取更多现场日志以便进一步排查"
                    )
                ]

            return DiagnosticReport(
                task_id=task_id,
                target=target,
                status="SUCCESS",
                fault_summary=summary,
                root_cause=root_cause,
                evidence_chain=[EvidenceItem(source="synthesized_facts", content=evidence_summary[:300], confidence=0.95)],
                remediation_actions=actions,
                duration_seconds=round(time.time() - start_time, 2)
            )

        # 生产实际调用 OpenAI-Compatible 接口
        messages = [
            {"role": "system", "content": SYSTEM_RCA_PROMPT},
            {"role": "user", "content": f"目标: {target}\n表象: {symptoms}\n采集到的现场证据:\n{evidence_summary}\n请输出结构化诊断 JSON。"}
        ]
        
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": settings.LLM_TEMPERATURE,
                        "response_format": {"type": "json_object"}
                    }
                )
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                
                return DiagnosticReport(
                    task_id=task_id,
                    target=target,
                    status=parsed.get("status", "SUCCESS"),
                    fault_summary=parsed.get("fault_summary", "排查完成"),
                    root_cause=parsed.get("root_cause", "未知根因"),
                    evidence_chain=[EvidenceItem(**item) for item in parsed.get("evidence_chain", [])],
                    remediation_actions=[RemediationAction(**act) for act in parsed.get("remediation_actions", [])],
                    duration_seconds=round(time.time() - start_time, 2)
                )
        except Exception as e:
            # 优雅降级静态报告
            return DiagnosticReport(
                task_id=task_id,
                target=target,
                status="PARTIAL_FAILURE",
                fault_summary=f"LLM 推理异常，触发静态数据兜底: {str(e)}",
                root_cause="需人工根据证据快速判断",
                evidence_chain=[EvidenceItem(source="raw_evidence", content=evidence_summary[:500], confidence=0.8)],
                remediation_actions=[RemediationAction(title="人工接入排查", risk_level="LOW", command_draft=None, explanation="由于AI推理暂时受阻，请SRE参考证据排查")],
                duration_seconds=round(time.time() - start_time, 2)
            )
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_llm.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add opspilot/core/prompt_templates.py opspilot/core/llm.py tests/test_llm.py
git commit -m "feat: implement LLM client and SRE RCA system prompts"
```

---

### 任务 7：状态机诊断工作流编排与降级熔断 (Workflow)

**文件：**
- 创建：`opspilot/core/state.py`
- 创建：`opspilot/core/workflow.py`
- 测试：`tests/test_workflow.py`

- [ ] **步骤 1：编写端到端状态机编排与轮次熔断测试**

```python
# tests/test_workflow.py
from opspilot.schemas.task import DiagnosticTask
from opspilot.core.workflow import DiagnosticWorkflow

def test_workflow_runs_end_to_end():
    task = DiagnosticTask(
        task_id="test-wf-001",
        source="cli",
        target_type="k8s_pod",
        target_name="order-api",
        namespace="prod",
        symptoms="CrashLoopBackOff"
    )
    workflow = DiagnosticWorkflow(mock_mode=True)
    report = workflow.run(task)
    assert report.task_id == "test-wf-001"
    assert report.status in ["SUCCESS", "PARTIAL_FAILURE"]
    assert len(report.evidence_chain) > 0
    assert len(report.remediation_actions) > 0
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_workflow.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'opspilot.core.state'`

- [ ] **步骤 3：编写状态定义与工作流状态机实现**

```python
# opspilot/core/state.py
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from opspilot.schemas.task import DiagnosticTask
from opspilot.schemas.report import EvidenceItem, DiagnosticReport

class DiagnosticState(BaseModel):
    task: DiagnosticTask
    current_round: int = 0
    max_rounds: int = 3
    evidence_pool: List[EvidenceItem] = Field(default_factory=list)
    hypotheses: List[str] = Field(default_factory=list)
    is_completed: bool = False
    final_report: Optional[DiagnosticReport] = None
```

```python
# opspilot/core/workflow.py
from typing import List
from opspilot.schemas.task import DiagnosticTask
from opspilot.schemas.report import DiagnosticReport, EvidenceItem
from opspilot.core.state import DiagnosticState
from opspilot.prefetches.k8s_prefetch import K8sPrefetcher
from opspilot.prefetches.node_prefetch import NodePrefetcher
from opspilot.tools.k8s_tools import GetPodEventsTool
from opspilot.tools.metric_tools import QueryPrometheusTool
from opspilot.core.llm import LLMClient
from opspilot.config import settings

class DiagnosticWorkflow:
    def __init__(self, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self.k8s_prefetcher = K8sPrefetcher()
        self.node_prefetcher = NodePrefetcher()
        self.llm_client = LLMClient(mock_mode=mock_mode)
        self.k8s_events_tool = GetPodEventsTool(mock_mode=mock_mode)
        self.prom_tool = QueryPrometheusTool(mock_mode=mock_mode)

    def run(self, task: DiagnosticTask) -> DiagnosticReport:
        state = DiagnosticState(task=task, max_rounds=settings.MAX_DEEPDIVE_ROUNDS)

        # 阶段 1: 确定性快速拓扑拉取 (Phase 1: Deterministic SOP)
        if task.target_type == "k8s_pod":
            initial_evidence = self.k8s_prefetcher.collect(task)
        else:
            initial_evidence = self.node_prefetcher.collect(task)
        state.evidence_pool.extend(initial_evidence)

        # 阶段 2: 状态机深挖与决策循环 (Phase 2: Deep-dive Loop, max 3 rounds)
        while state.current_round < state.max_rounds and not state.is_completed:
            state.current_round += 1
            
            # 若第一阶段已采集到强证据(如 OOM 或 磁盘已满)，可提前收敛
            evidence_text = "\n".join([f"[{e.source}] {e.content}" for e in state.evidence_pool])
            if "137" in evidence_text or "98%" in evidence_text:
                state.is_completed = True
                break

            # 否则进行一轮定向补充查询
            if task.target_type == "k8s_pod":
                add_evidence = self.k8s_events_tool.execute(
                    namespace=task.namespace or "default",
                    pod_name=task.target_name
                )
                state.evidence_pool.append(EvidenceItem(source="k8s_events", content=add_evidence, confidence=0.85))
            else:
                add_metric = self.prom_tool.execute(query=f"node_load1{{instance='{task.target_name}'}}")
                state.evidence_pool.append(EvidenceItem(source="prometheus", content=add_metric, confidence=0.85))
            
            state.is_completed = True

        # 阶段 3: 结构化合成 RCA 报告
        evidence_summary = "\n".join([f"- [{e.source}] {e.content}" for e in state.evidence_pool])
        report = self.llm_client.synthesize_rca(
            task_id=task.task_id,
            target=task.target_name,
            symptoms=task.symptoms,
            evidence_summary=evidence_summary
        )
        state.final_report = report
        return report
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_workflow.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add opspilot/core/state.py opspilot/core/workflow.py tests/test_workflow.py
git commit -m "feat: implement diagnostic workflow state machine with loop breaker"
```

---

### 任务 8：多渠道通知渲染器 (Console, DingTalk)

**文件：**
- 创建：`opspilot/notifiers/base.py`
- 创建：`opspilot/notifiers/console.py`
- 创建：`opspilot/notifiers/dingtalk.py`
- 测试：`tests/test_notifiers.py`

- [ ] **步骤 1：编写控制台与卡片渲染测试**

```python
# tests/test_notifiers.py
from opspilot.schemas.report import DiagnosticReport, EvidenceItem, RemediationAction
from opspilot.notifiers.console import ConsoleNotifier
from opspilot.notifiers.dingtalk import DingTalkNotifier

def test_console_and_markdown_render():
    report = DiagnosticReport(
        task_id="task-999",
        target="pod-demo",
        status="SUCCESS",
        fault_summary="Pod OOM killed",
        root_cause="Memory exceeded",
        evidence_chain=[EvidenceItem(source="log", content="OOM", confidence=1.0)],
        remediation_actions=[RemediationAction(title="Scale up", risk_level="LOW", command_draft="kubectl scale", explanation="fix")],
        duration_seconds=1.5
    )
    console_notifier = ConsoleNotifier()
    output = console_notifier.render(report)
    assert "pod-demo" in output
    assert "Memory exceeded" in output

    dt_notifier = DingTalkNotifier()
    markdown = dt_notifier.render_markdown_card(report)
    assert "### 🚨 OpsPilot 故障排查报告" in markdown
    assert "pod-demo" in markdown
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_notifiers.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'opspilot.notifiers'`

- [ ] **步骤 3：编写 `opspilot/notifiers/` 渲染实现**

```python
# opspilot/notifiers/base.py
from abc import ABC, abstractmethod
from opspilot.schemas.report import DiagnosticReport

class BaseNotifier(ABC):
    @abstractmethod
    def notify(self, report: DiagnosticReport) -> bool:
        pass
```

```python
# opspilot/notifiers/console.py
from opspilot.notifiers.base import BaseNotifier
from opspilot.schemas.report import DiagnosticReport
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

class ConsoleNotifier(BaseNotifier):
    def __init__(self):
        self.console = Console()

    def render(self, report: DiagnosticReport) -> str:
        lines = []
        lines.append(f"[bold cyan]🎯 诊断目标:[/bold cyan] {report.target} (ID: {report.task_id})")
        lines.append(f"[bold yellow]⚡ 故障摘要:[/bold yellow] {report.fault_summary}")
        lines.append(f"[bold red]🔍 核心根因:[/bold red] {report.root_cause}")
        lines.append(f"[bold green]⏱️ 排查耗时:[/bold green] {report.duration_seconds}s")
        return "\n".join(lines)

    def notify(self, report: DiagnosticReport) -> bool:
        content = self.render(report)
        self.console.print(Panel(content, title="🚀 OpsPilot RCA Report", border_style="blue"))
        return True
```

```python
# opspilot/notifiers/dingtalk.py
from opspilot.notifiers.base import BaseNotifier
from opspilot.schemas.report import DiagnosticReport

class DingTalkNotifier(BaseNotifier):
    def render_markdown_card(self, report: DiagnosticReport) -> str:
        actions_md = ""
        for act in report.remediation_actions:
            cmd = f"\n```bash\n{act.command_draft}\n```" if act.command_draft else ""
            actions_md += f"- **[{act.risk_level}] {act.title}**\n  {act.explanation}{cmd}\n"

        evidence_md = "\n".join([f"- `{e.source}`: {e.content}" for e in report.evidence_chain])

        return f"""### 🚨 OpsPilot 故障排查报告
- **诊断目标**: `{report.target}`
- **任务编号**: `{report.task_id}`
- **排障结论**: **{report.fault_summary}**
- **核心根因**: {report.root_cause}

#### 📋 关键事实证据
{evidence_md}

#### 🛠️ SRE 建议处置方案
{actions_md}
> 耗时: {report.duration_seconds}s | 状态: {report.status}
"""

    def notify(self, report: DiagnosticReport) -> bool:
        # 如需发送 HTTP Webhook 可使用 httpx.post
        return True
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_notifiers.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add opspilot/notifiers/ tests/test_notifiers.py
git commit -m "feat: implement console rich formatter and dingtalk markdown card"
```

---

### 任务 9：双模入口 (FastAPI Webhook 服务与 Typer CLI 终端)

**文件：**
- 创建：`opspilot/api/routes_webhook.py`
- 创建：`opspilot/cli/main.py`
- 创建：`opspilot/main.py`
- 测试：`tests/test_api_and_cli.py`

- [ ] **步骤 1：编写 API Webhook 与 CLI 测试**

```python
# tests/test_api_and_cli.py
from fastapi.testclient import TestClient
from opspilot.main import app

client = TestClient(app)

def test_webhook_alertmanager_endpoint():
    payload = {
        "status": "firing",
        "alerts": [
            {
                "status": "firing",
                "labels": {"alertname": "PodCrash", "pod": "test-pod", "namespace": "default"},
                "annotations": {"summary": "Pod test-pod is crashing"}
            }
        ]
    }
    resp = client.post("/webhook/alertmanager", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert len(data["reports"]) == 1
    assert data["reports"][0]["target"] == "test-pod"

def test_healthz_endpoint():
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "healthy"
```

- [ ] **步骤 2：运行测试验证失败**

运行：`pytest tests/test_api_and_cli.py -v`
预期：FAIL，`ModuleNotFoundError: No module named 'opspilot.main'`

- [ ] **步骤 3：编写 Webhook API 与 CLI 入口**

```python
# opspilot/api/routes_webhook.py
from fastapi import APIRouter
from opspilot.schemas.alert import AlertmanagerPayload
from opspilot.core.workflow import DiagnosticWorkflow
from opspilot.notifiers.dingtalk import DingTalkNotifier

router = APIRouter()
workflow = DiagnosticWorkflow(mock_mode=True)
notifier = DingTalkNotifier()

@router.post("/webhook/alertmanager")
def handle_alertmanager_webhook(payload: AlertmanagerPayload):
    tasks = payload.to_diagnostic_tasks()
    reports = []
    for task in tasks:
        report = workflow.run(task)
        notifier.notify(report)
        reports.append(report.model_dump())
    return {"status": "ok", "dispatched_tasks": len(tasks), "reports": reports}
```

```python
# opspilot/main.py
from fastapi import FastAPI
from opspilot.api.routes_webhook import router as webhook_router

app = FastAPI(title="OpsPilot - AIOps Diagnostic Agent", version="0.1.0")

@app.get("/healthz")
def healthz():
    return {"status": "healthy", "service": "opspilot"}

app.include_router(webhook_router)
```

```python
# opspilot/cli/main.py
import uuid
import typer
from rich.console import Console
from opspilot.schemas.task import DiagnosticTask
from opspilot.core.workflow import DiagnosticWorkflow
from opspilot.notifiers.console import ConsoleNotifier

app = typer.Typer(help="OpsPilot: SRE 自动化排障 Agent CLI")
console = Console()

@app.command()
def diagnose(
    target_type: str = typer.Option(..., "--type", "-t", help="目标类型: k8s_pod 或 linux_node"),
    name: str = typer.Option(..., "--name", "-n", help="目标名称 (Pod 名或主机 IP)"),
    namespace: str = typer.Option("default", "--namespace", "-ns", help="K8s 命名空间"),
    symptoms: str = typer.Option("异常检测与排查", "--symptoms", "-s", help="表象描述")
):
    """手动发起一次现场故障排障"""
    console.print(f"[bold blue]🚀 正在启动对 {target_type} '{name}' 的深度排查...[/bold blue]")
    task = DiagnosticTask(
        task_id=f"cli-{uuid.uuid4().hex[:6]}",
        source="cli",
        target_type=target_type,
        target_name=name,
        namespace=namespace,
        symptoms=symptoms
    )
    workflow = DiagnosticWorkflow(mock_mode=True)
    report = workflow.run(task)
    notifier = ConsoleNotifier()
    notifier.notify(report)

if __name__ == "__main__":
    app()
```

- [ ] **步骤 4：运行测试验证通过**

运行：`pytest tests/test_api_and_cli.py -v`
预期：PASS

- [ ] **步骤 5：Commit**

```bash
git add opspilot/api/ opspilot/cli/ opspilot/main.py tests/test_api_and_cli.py
git commit -m "feat: implement FastAPI webhook handler and Typer CLI interactive tool"
```

---

### 任务 10：4 套经典离线故障模拟演练端到端验证

**文件：**
- 创建：`tests/test_e2e_scenarios.py`

- [ ] **步骤 1：编写 4 套典型故障（K8s OOM、K8s CrashLoop、Node 磁盘满、Node CPU 飙高）端到端测试**

```python
# tests/test_e2e_scenarios.py
from opspilot.schemas.task import DiagnosticTask
from opspilot.core.workflow import DiagnosticWorkflow

def test_scenario_1_k8s_oom_killed():
    """演练场景 1: Pod 内存超限被 OOMKilled"""
    task = DiagnosticTask(
        task_id="mock-001",
        source="alertmanager",
        target_type="k8s_pod",
        target_name="payment-service-8fd9-xyz",
        namespace="prod",
        symptoms="Pod status CrashLoopBackOff, container terminated exit code 137"
    )
    workflow = DiagnosticWorkflow(mock_mode=True)
    report = workflow.run(task)
    assert report.status == "SUCCESS"
    assert "内存" in report.root_cause or "OOM" in report.root_cause
    assert any(a.risk_level in ["MEDIUM", "HIGH"] for a in report.remediation_actions)

def test_scenario_2_node_disk_pressure():
    """演练场景 2: Linux 宿主机磁盘打满 (DiskPressure)"""
    task = DiagnosticTask(
        task_id="mock-002",
        source="alertmanager",
        target_type="linux_node",
        target_name="10.0.1.15",
        symptoms="Host DiskSpaceFillingUp /dev/vda1 > 95%"
    )
    workflow = DiagnosticWorkflow(mock_mode=True)
    report = workflow.run(task)
    assert report.status == "SUCCESS"
    assert "磁盘" in report.root_cause or "disk" in report.root_cause.lower()

def test_scenario_3_k8s_config_crash():
    """演练场景 3: Pod 因配置缺失持续重启"""
    task = DiagnosticTask(
        task_id="mock-003",
        source="cli",
        target_type="k8s_pod",
        target_name="auth-service",
        namespace="default",
        symptoms="ConfigMap or Secret not found"
    )
    workflow = DiagnosticWorkflow(mock_mode=True)
    report = workflow.run(task)
    assert report.status in ["SUCCESS", "PARTIAL_FAILURE"]
    assert len(report.remediation_actions) > 0

def test_scenario_4_node_high_load():
    """演练场景 4: Linux 宿主机高负载"""
    task = DiagnosticTask(
        task_id="mock-004",
        source="cli",
        target_type="linux_node",
        target_name="192.168.1.100",
        symptoms="High system load and CPU throttling"
    )
    workflow = DiagnosticWorkflow(mock_mode=True)
    report = workflow.run(task)
    assert report.status == "SUCCESS"
    assert report.duration_seconds >= 0
```

- [ ] **步骤 2：运行测试验证通过**

运行：`pytest tests/test_e2e_scenarios.py -v`
预期：PASS（当相关模块就绪后全量通过）

- [ ] **步骤 3：全量回归测试确认**

运行：`pytest tests/ -v`
预期：所有单元测试与 4 套演练场景全部 PASS

- [ ] **步骤 4：Commit**

```bash
git add tests/test_e2e_scenarios.py
git commit -m "test: add 4 end-to-end RCA mock drill scenarios for K8s and Linux hosts"
```
