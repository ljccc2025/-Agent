# 自动化运维排障 Agent (OpsPilot) 设计规格说明书

- **日期**：2026-09-03
- **版本**：v1.0.0
- **状态**：已评审 (Approved)

---

## 1. 背景与目标 (Background & Goals)

### 1.1 业务背景
在现代化云原生与分布式生产环境中，监控告警（如 Prometheus/Alertmanager）频繁触发。然而，从告警发出到 SRE 人工接入、收集排障上下文、推导根因、给出处置方案往往耗时 15~30 分钟以上，且大量中低级告警具备高度可重复的排查逻辑（如 OOMKilled、配置错误、磁盘打满等）。

### 1.2 核心目标
构建一个生产级、轻量且高度可控的**自动化故障排查与根因分析（RCA - Root Cause Analysis）Agent**（代号 **OpsPilot**）：
1. **故障精准定位**：聚焦只读根因分析，实现告警发生后 30 秒内自动聚合关联事实并完成因果推导。
2. **混合架构覆盖**：同时支持云原生 **Kubernetes 容器环境**（Pod/Workload/Events/Logs）与经典 **Linux 宿主机/虚拟机环境**（CPU/Memory/Disk/Systemd/dmesg）。
3. **双模驱动**：支持作为 Webhook 机器人自动监听告警并推送群聊卡片，同时支持 SRE 在命令行 CLI / API 中主动发起交互式追问排查。
4. **安全落地**：坚守“纯只读沙箱 + 敏感脱敏 + 人机确认（Human-in-the-Loop）”，绝不在无人工授权下对生产发起破坏性写操作。

---

## 2. 总体架构设计 (System Architecture)

### 2.1 分层两阶段架构 (Hierarchical Two-Phase Architecture)
系统采用**“确定性 SOP 预聚合 + 状态机 ReAct 深度探查”**的两阶段架构：

```
                             [ 输入层 (Input Layer) ]
                   ┌─────────────────────────────────────────┐
                   │  1. 告警 Webhook (Alertmanager 等)      │
                   │  2. SRE 交互式 CLI / HTTP API           │
                   └────────────────────┬────────────────────┘
                                        │
                                        ▼
                   [ 任务标准化层 (Task Normalization) ]
                   ┌─────────────────────────────────────────┐
                   │   解析并转换为统一 DiagnosticTask 契约   │
                   └────────────────────┬────────────────────┘
                                        │
                                        ▼
              [ Phase 1: 确定性 SOP 预聚合 (Deterministic Fast Path) ]
                   ┌─────────────────────────────────────────┐
                   │ 规则路由识别：K8s Pod 异常 / Linux 主机异常 │
                   │ 并行拉取基础拓扑证据：Top资源/状态/近100行日志 │
                   │ 耗时 < 2s，组装第一阶证据集 (EvidenceSet)   │
                   └────────────────────┬────────────────────┘
                                        │
                                        ▼
             [ Phase 2: 状态机智能深挖 (LangGraph Reasoning Engine) ]
                   ┌─────────────────────────────────────────┐
                   │ - 状态分析与假设提出 (Hypothesis)       │
                   │ - 针对性只读工具调用 (Tool Calling)     │
                   │ - 证据验证与排除 (Verification)         │
                   │ - 硬熔断保护 (最多 3 轮探查循环)         │
                   └───────────┬─────────────────▲───────────┘
                               │                 │ (按需调取)
                               ▼                 │
                   ┌─────────────────────────────┴───────────┐
                   │       只读工具箱 (Tool Registry)        │
                   │  - K8s API (Events / Pod Logs / Pod YAML)│
                   │  - Host Inspector (ps, df, systemd)     │
                   │  - Prometheus PromQL (时序度量趋势)     │
                   │  - Loki LogQL (跨应用日志过滤)          │
                   └─────────────────────────────────────────┘
                                        │
                                        ▼
                   [ 结构化报告生成 (Synthesis & Report) ]
                   ┌─────────────────────────────────────────┐
                   │ 输出 Pydantic 校验的 DiagnosticReport   │
                   │ 包含: 故障摘要、影响面、证据链、根因结论 │
                   │ 以及 SRE 分级处置建议（含命令模板草稿） │
                   └────────────────────┬────────────────────┘
                                        │
                                        ▼
                            [ 通知与呈现 (Egress) ]
                   ┌─────────────────────────────────────────┐
                   │ 1. 钉钉 / 飞书 / 企业微信 Markdown 卡片 │
                   │ 2. 命令行终端彩色流式展示 / API JSON     │
                   └─────────────────────────────────────────┘
```

---

## 3. 核心模块与代码组织 (Component Specification)

```text
opspilot/
├── api/                      # Web API 服务 (FastAPI)
│   ├── routes_webhook.py     # 接收 Alertmanager 告警 Webhook
│   └── routes_diagnose.py    # 交互式排查 API (手动触发/追问)
├── cli/                      # 命令行客户端 (Typer)
│   └── main.py               # opspilot diagnose pod/node 命令入口
├── core/                     # Agent 核心大脑与状态机
│   ├── state.py              # LangGraph 状态定义 (DiagnosticState)
│   ├── workflow.py           # 诊断工作流编排器
│   ├── prompt_templates.py   # 运维领域 RCA 提示词模板
│   └── llm.py                # 统一的 OpenAI 兼容客户端适配层
├── prefetches/               # Phase 1: 确定性 SOP 快速取证
│   ├── base.py               # 抽象预拉取接口
│   ├── k8s_prefetch.py       # K8s Pod 状态、最近日志、事件快速拉取
│   └── node_prefetch.py      # Linux 主机 CPU/Mem/Disk/dmesg 快速拉取
├── tools/                    # Phase 2: LLM 可调用的只读工具集
│   ├── base.py               # 只读安全装饰器与基类
│   ├── k8s_tools.py          # K8s 只读工具
│   ├── host_tools.py         # Linux 主机只读工具 (带严格命令白名单)
│   ├── metric_tools.py       # Prometheus PromQL 工具
│   └── log_tools.py          # Loki 工具
├── notifiers/                # 报告通知推送
│   ├── base.py               # 通知器基类
│   ├── dingtalk.py           # 钉钉机器人卡片
│   ├── feishu.py             # 飞书卡片消息
│   └── console.py            # 终端控制台彩色输出
├── schemas/                  # 全局 Pydantic 数据契约
│   ├── task.py               # DiagnosticTask 统一任务定义
│   ├── report.py             # DiagnosticReport 结构化报告模型
│   └── alert.py              # Alertmanager 告警载荷模型
├── config.py                 # 应用配置与环境变量加载
└── main.py                   # 服务启动入口
```

---

## 4. 数据契约定义 (Data Models)

### 4.1 诊断任务模型 (`schemas/task.py`)
```python
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class DiagnosticTask(BaseModel):
    task_id: str = Field(..., description="唯一任务追踪 ID")
    source: str = Field(..., description="来源: alertmanager / cli / manual_api")
    target_type: str = Field(..., description="目标类型: k8s_pod / linux_node")
    target_name: str = Field(..., description="目标名称: 如 default/order-service-xxx 或 192.168.1.10")
    namespace: Optional[str] = Field(None, description="命名空间(若为 K8s)")
    alert_name: Optional[str] = Field(None, description="关联告警名称")
    alert_labels: Dict[str, Any] = Field(default_factory=dict)
    symptoms: str = Field(..., description="故障初始表象描述")
```

### 4.2 结构化 RCA 报告模型 (`schemas/report.py`)
```python
from pydantic import BaseModel, Field
from typing import List, Optional

class EvidenceItem(BaseModel):
    source: str = Field(..., description="证据来源: pod_log / k8s_event / prometheus / dmesg")
    content: str = Field(..., description="事实内容提要（如: OOMKilled detected, exit code 137）")
    confidence: float = Field(default=1.0, description="证据可信度 0~1.0")

class RemediationAction(BaseModel):
    title: str = Field(..., description="处置动作名称")
    risk_level: str = Field(..., description="风险等级: LOW / MEDIUM / HIGH")
    command_draft: Optional[str] = Field(None, description="建议执行的命令模板，供人类复制确认")
    explanation: str = Field(..., description="为何执行此动作及预期影响")

class DiagnosticReport(BaseModel):
    task_id: str
    target: str
    status: str = Field(..., description="诊断状态: SUCCESS / PARTIAL_FAILURE / UNRESOLVED")
    fault_summary: str = Field(..., description="一句话故障摘要")
    root_cause: str = Field(..., description="定位出的核心根因结论")
    evidence_chain: List[EvidenceItem] = Field(default_factory=list, description="推导支撑证据链")
    remediation_actions: List[RemediationAction] = Field(default_factory=list, description="建议处置方案")
    duration_seconds: float = Field(..., description="排查总耗时")
```

---

## 5. 安全沙箱与防护体系 (Security Sandbox & Guardrails)

1. **底层 RBAC 只读限制**：
   - K8s 运行身份绑定最小权限 ClusterRole，仅包含 `["get", "list", "watch"]` 动词，物理隔离写操作。
2. **主机命令绝对白名单**：
   - 仅放行以下预置安全指令：`uptime`, `free`, `df`, `ps`, `top`, `journalctl`, `systemctl status`, `dmesg`, `ss`。
   - 系统调用一律采用参数化列表（`subprocess.run([...], shell=False)`），绝不通过字符串拼接执行命令。
3. **数据敏感信息流式脱敏 (Redaction)**：
   - 采集到的日志、YAML 配置与输出结果经脱敏引擎过滤：
     - 正则匹配并替换 API Key、Token、Password、AK/SK、IP 敏感段为 `***REDACTED***`。
4. **人机协同确认机制 (Human-in-the-Loop)**：
   - Agent 只出具处置建议与命令草稿，严禁自动执行破坏性修复，最终执行权 100% 归属于人类 SRE。

---

## 6. 容错降级与测试策略 (Fault Tolerance & Verification)

### 6.1 降级策略
- **监控源失联降级**：若 Prometheus 或 Loki 响应超时（>8s），降级为仅依据 K8s 事件和本地日志诊断，并在报告中显式声明。
- **LLM 异常静态兜底**：若大模型 API 遭遇限流或故障，触发 Fallback 引擎直接输出 Phase 1 采集到的原始健康数据与最近错误日志卡片，确保关键现场不丢失。
- **探查轮次熔断**：LangGraph 状态机严格限定探查深度上限为 3 次循环，到达上限后强制收敛输出。

### 6.2 测试与演练验证
- **单元测试**：针对 Alertmanager JSON 解析、命令白名单拦截、敏感脱敏过滤器编写 100% 覆盖测试。
- **内置 4 套离线离线演练场景 (Mock Scenarios)**：
  1. `k8s_pod_crash_loop`: 缺失配置文件导致应用启动退出。
  2. `k8s_pod_oom_killed`: 内存超限 Exit 137。
  3. `linux_node_disk_pressure`: 根目录磁盘满 98%。
  4. `linux_host_high_cpu`: 死循环进程打满 CPU。
- 保证在离线无集群环境下也能完成全链路逻辑验证。
