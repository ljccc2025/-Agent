# OpsPilot AI 自动化运维排障智能体 — 全栈技术方案与系统架构文档

---

## 一、需求深度复述与分析

### 1.1 功能模块分析

| 功能模块 | 需求描述 | 技术要求 | 优先级 |
|---------|---------|---------|--------|
| 告警 Webhook 接入 | 接收 Alertmanager、Prometheus、云监控告警推送 | 高吞吐异步 Webhook 接收、请求去重与防抖、告警 Payload 标准化 | P0 |
| 任务标准化分诊 | 自动识别故障实体类型（K8s Pod 还是 Linux Node）并提取诊断元数据 | 规则匹配器 + 正则抽取 + 标签拓扑映射（Namespace/Host/Service） | P0 |
| Phase 1 确定性 SOP 取证 | 告警触发后 2s 内自动完成第一阶客观事实快照收集 | 并发非阻塞调用、Pod describe/近百行日志/Events/主机 df/free/dmesg | P0 |
| Phase 2 状态机智能深挖 | 基于假设检验（Hypothesis-Testing）按需调用工具深入排查 | LangGraph 状态机编排、只读 Tool Calling、最多 3 轮硬熔断保护 | P0 |
| Prometheus PromQL 探针 | 查询故障时刻前后时序指标（CPU/内存/磁盘IO/网络丢包等） | HTTP GET 只读查询、指标数据点截断（防上下文撑爆）、超时保护 | P0 |
| Loki / 日志流检索 | 跨应用集中式错误日志回溯与上下文模式匹配 | LogQL 只读查询、多行日志聚类、过滤关键词高亮 | P1 |
| 只读安全沙箱 | 严禁对生产执行任何写操作与破坏性指令 | 底层 RBAC 权限隔离（仅 get/list/watch）+ 主机命令绝对白名单校验 | P0 |
| 数据敏感信息流式脱敏 | 日志、配置中的密码、Token、AK/SK 自动脱敏 | 正则流水线过滤替换为 `***REDACTED***`，保障数据合规不出境 | P0 |
| 结构化 RCA 报告生成 | 输出包含故障摘要、根因结论、证据链及处置建议的报告 | Pydantic Schema 强校验输出、防模型幻觉与字段缺失 | P0 |
| SRE 分级处置建议 | 生成带 LOW/MEDIUM/HIGH 风险等级的命令草稿 | 命令模板语法生成、人工审批（Human-in-the-Loop）确认机制 | P0 |
| 钉钉/飞书/企微机器人通知 | 排查完成后向告警群推送富文本 Markdown 诊断卡片 | 各 IM 平台 Webhook 客户端、Markdown 模板渲染、一键跳转 | P1 |
| SRE 交互式 ChatOps (CLI) | 运维工程师通过终端命令行主动发起追问与故障排障 | Typer 命令行框架 + Rich 彩色终端流式排版渲染 | P0 |
| Web 控制台与大屏看板 | 提供暗黑极客风格的仪表盘，展示热力图、RCA 报告库与体征 | Tailwind CSS + 响应式布局 + 时序热力图 + 甜甜圈图表 | P1 |
| 离线故障演练与 Mock 验证 | 无需真实云环境即可一键跑通 4 大典型故障全流程验证 | 内置 OOM、CrashLoop、磁盘打满、高负载 4 组离线测试夹具 | P0 |
| 故障知识库与导出复盘 | 历史排障记录归档、PDF/JSON 报告导出 | SQLite/本地 JSON 存储 + 导出为标准 Post-Mortem 复盘文档 | P1 |

### 1.2 非功能需求分析

| 需求维度 | 具体要求 | 技术挑战 |
|---------|---------|---------|
| **排障时效性 (MTTR)** | 告警到达后 30 秒内出具完整的根因报告与处置建议 | 传统 LLM 多轮 ReAct 耗时极长，必须采用确定性 SOP 预取优化 |
| **绝对安全性 (Safety)** | 生产零误操作风险，100% 只读运行，杜绝命令注入 | 需在系统调用层拦截 `shell=True`，维护绝对命令白名单 |
| **高可用与容错** | 监控数据源（Prometheus/Loki）失联或大模型限流时不崩溃 | 状态机降级容错、SOP 静态数据兜底简报机制 |
| **模型无关性** | 支持公有云模型（DeepSeek/Qwen/OpenAI）及本地私有化部署（Ollama） | 统一 OpenAI 兼容 SDK 抽象，基于环境变量一键切换 |
| **跨平台环境** | 支持 Linux 服务器环境、K8s 容器化集群运行，同时兼容 Windows 开发机 | 抽象 OS 调用接口、提供标准化 Dockerfile 与 Helm Chart |
| **资源轻量占用** | Agent 运行时内存占用 < 200MB，CPU 消耗低 | 采用 Python 异步非阻塞 IO (FastAPI + HTTPX)，杜绝重量级依赖 |

### 1.3 隐含技术挑战

| 挑战 | 描述 | 影响范围 |
|-----|------|---------|
| **LLM 上下文溢出** | 生产日志动辄上万行，时序数据点数万，极易挤爆大模型上下文并产生高昂费用 | 日志截断算法、TopK 关键行提取、时序降采样 |
| **Agent 推理死循环** | 纯 ReAct 智能体在面对模糊故障时容易在多个查询工具之间无限打转 | 状态机设置最大轮次熔断（Max 3 Rounds），强制收敛 |
| **数据脱敏漏判** | 敏感连接串格式千变万化，若泄露至大模型可能引发安全审计事故 | 多重正则引擎匹配多种 Token 与凭据模式 |
| **告警风暴并发压垮** | 生产大规模级联故障时，同一时间涌入成百上千条告警 | 异步任务队列、告警去重防抖（Deduplication）机制 |
| **混合异构环境抽象** | 容器环境使用 K8s API，传统节点使用 SSH/本地 Shell，接口差异巨大 | 统一抽象 `BaseDiagnosticTool` 与统一事件状态契约 |

### 1.4 本系统与传统运维脚本/普通告警机器人的本质区别

| 对比维度 | OpsPilot AI 智能体 | 传统脚本自动化 (Shell/Ansible) | 普通告警机器人 (Prometheus Alert Hook) |
|---------|-------------------|-----------------------------|-------------------------------------|
| **分析深度** | **多模态因果推导 (RCA)**：关联指标、日志、事件推导根本诱因 | 只能执行硬编码规则，无因果推导能力 | 仅透传告警原始标题和阈值，无排查分析 |
| **上下文感知** | **自动跨层下钻**：自动关联宿主机与容器层指标拓扑 | 需人工指定服务器与参数执行指定脚本 | 孤立告警，无上下游关联拓扑 |
| **自适应调整** | **状态机动态深挖**：一阶证据不足时自动补充调取 PromQL/日志 | 流程死板，遇到非预期输出直接报错退出 | 无反馈能力 |
| **交互形态** | **双模驱动**：支持告警自动诊断与 SRE 交互式命令行对话追问 | 主要是静态脚本，交互成本高 | 单向通知推送，不支持反向提问追问 |
| **安全控制** | **只读沙箱 + 建议命令草稿**：兼顾安全防线与人工快速操作 | 很多脚本带写操作，一旦误判破坏力巨大 | 无执行能力 |

---

## 二、终极技术栈选型（带具体版本及决策矩阵）

### 2.1 后端服务与 Webhook 调度框架

| 维度 | 详情 |
|------|------|
| **我们的选择** | **FastAPI 0.115.0 + Uvicorn 0.30.6** |
| 备选方案 | Flask 3.x、Django 5.x、Go Gin |
| 决定性理由 | 1) 原生异步（async/await）支持高并发 Webhook 接入，告警风暴不阻塞；2) 基于 Pydantic v2 提供强类型入参校验与 OpenAPI 自动文档；3) 内存开销极小（冷启动内存 < 40MB）；4) Python 生态与大模型/数据分析工具链无缝集成 |
| 关键应用点 | `/webhook/alertmanager` 告警接收路由、`/api/v1/diagnose` 交互排查 API、健康检查 `/healthz` |

### 2.2 Agent 编排框架与状态机

| 维度 | 详情 |
|------|------|
| **我们的选择** | **自研轻量两阶段状态机 + LangGraph 0.2.x 状态模型** |
| 备选方案 | AutoGen 0.4、CrewAI 0.5、纯 LangChain AgentExecutor |
| 决定性理由 | 1) 运维排障对确定性和延迟极其敏感，重型 Agent 框架不可控且多 Agent 间无谓聊天浪费 Token；2) 分层两阶段架构（Phase 1 确定性 SOP + Phase 2 限制轮次深挖）具备 100% 可解释性与硬熔断能力；3) LangGraph 的 StateGraph 状态流可精确记录推导历史与证据池变更 |
| 关键应用点 | `DiagnosticState` 状态流转（Prefetch ➔ Reason ➔ DeepDive ➔ Synthesize ➔ Completed） |

### 2.3 大模型推理引擎与接入规范

| 维度 | 详情 |
|------|------|
| **我们的选择** | **DeepSeek-V3/R1 + OpenAI SDK 1.50.x（完全兼容协议）** |
| 备选方案 | 闭源 OpenAI GPT-4o、Claude 3.5 Sonnet、自建本地 vLLM |
| 决定性理由 | 1) DeepSeek API 完全兼容 OpenAI SDK 格式（仅需配置 `base_url`），零迁移成本；2) 针对复杂排障推导能力卓越，中文错误日志和报错堆栈理解远超同类模型；3) 成本极低（百万 Token 仅数元），适合生产环境全天候告警排障；4) 兼容本地 Ollama（如 `qwen2.5:14b`），断网离线环境一键平滑切换 |
| 关键应用点 | 系统 RCA System Prompt 约束、JSON 模式输出校验、证据链因果归纳 |

### 2.4 云原生 Kubernetes 客户端与探针

| 维度 | 详情 |
|------|------|
| **我们的选择** | **kubernetes 31.0.0 (官方 Python SDK) + subprocess kubectl 原生 CLI 适配器** |
| 备选方案 | pykube-ng、纯 HTTP 请求 K8s API |
| 决定性理由 | 1) 双轨驱动：环境具备 `kubectl` 时优先调用原生 CLI（获取与人类 SRE 完全一致的 describe 与 tail logs 输出，鲁棒性极强）；2) 官方 SDK 提供精确的事件过滤与 API 类型约束；3) 支持 In-Cluster ServiceAccount 与 Out-of-Cluster kubeconfig 双认证 |
| 关键应用点 | Pod 状态查询、`--previous` 崩溃日志提取、InvolvedObject 关联 Events 拉取 |

### 2.5 Linux 宿主机探针与命令安全沙箱

| 维度 | 详情 |
|------|------|
| **我们的选择** | **Python subprocess (参数化执行) + 绝对命令白名单校验器 + Paramiko 3.5.0 (远程 SSH)** |
| 备选方案 | Ansible Runner、SaltStack API、Fabric |
| 决定性理由 | 1) 严禁 `shell=True`，彻底杜绝 `; rm -rf /` 或管道注入风险；2) 维护封闭的只读命令白名单（仅放行 `df`, `free`, `uptime`, `systemctl status`, `journalctl`, `dmesg`, `ps`, `top` 等）；3) 兼顾本地节点运行与跳板机 SSH 远程纳管节点 |
| 关键应用点 | 宿主机根分区与挂载点磁盘检查、系统内存空闲分析、内核故障日志排查 |

### 2.6 时序监控与日志检索客户端

| 维度 | 详情 |
|------|------|
| **我们的选择** | **HTTPX 0.27.2 (异步非阻塞) + Prometheus HTTP API + Loki LogQL HTTP API** |
| 备选方案 | prometheus-api-client、requests 同步调用 |
| 决定性理由 | 1) HTTPX 提供纯异步连接池与严格的超时熔断（Timeout=8s）；2) 直接使用 Prometheus 标准 API（`/api/v1/query` 与 `/api/v1/query_range`），零额外繁重封装；3) 时序结果自动提取数值标量，将巨幅时序压缩为结构化事实片段 |
| 关键应用点 | CPU 限流度量、内存使用斜率、磁盘 IO 饱和度、Loki 错误日志过滤 |

### 2.7 前端 UI 架构与控制台

| 维度 | 详情 |
|------|------|
| **我们的选择** | **Tailwind CSS 3.4 + Plus Jakarta Sans 现代暗黑极客主题 + 原生响应式组件** |
| 备选方案 | Vue 3 Element-Plus、React Ant-Design |
| 决定性理由 | 1) 严格像素级还原高级暗黑 SaaS 仪表盘风格（冷蓝黑 `#0c0e17` 底色、`#131622` 卡片、电光紫蓝高光）；2) 单文件或极简依赖即可快速加载，无需复杂的构建打包流程，作为静态资产可直接内嵌在 FastAPI 服务中运行；3) 包含三行式复合布局、热力图矩阵、甜甜圈环形图、故障演练注入器与交互式 ChatOps |
| 关键应用点 | 运维监控总览大屏、RCA 根因报告交互卡片、故障快捷演练与排障终端 |

### 2.8 CLI 命令行交互客户端

| 维度 | 详情 |
|------|------|
| **我们的选择** | **Typer 0.12.5 + Rich 13.8.1** |
| 备选方案 | Click、Argparse、Prompt-Toolkit |
| 决定性理由 | 1) Typer 基于类型注解声明 CLI 参数，开发效率高，开箱即用 `--help`；2) Rich 提供工业级终端彩色排版、表格渲染、Panel 面板与 Markdown 格式化；3) 完美契合 SRE 在 Linux 终端、跳板机或本地 macOS/Windows 进行日常交互式排障 |
| 关键应用点 | `opspilot diagnose pod/node` 命令、`opspilot run-mock` 演练命令 |

### 2.9 数据契约与校验引擎

| 维度 | 详情 |
|------|------|
| **我们的选择** | **Pydantic 2.9.2 + Pydantic-Settings 2.5.2** |
| 备选方案 | Marshmallow、Attrs、dataclasses |
| 决定性理由 | 1) Pydantic v2 基于 Rust 核心重构，数据序列化性能提升 5~10 倍；2) 严格保证告警输入 `DiagnosticTask` 与输出 `DiagnosticReport` 的字段契约；3) 支持强类型环境变量解析（`.env` 自动读取） |
| 关键应用点 | 全局数据契约、大模型输出格式强约束、配置中心 |

### 2.10 告警通知与协作推送渠道

| 维度 | 详情 |
|------|------|
| **我们的选择** | **自研 Multi-Channel Notifier (DingTalk / Feishu / WeCom / Console)** |
| 备选方案 | Apprise、Prometheus Alertmanager 自身中继 |
| 决定性理由 | 1) 国内企业主流协作工具（钉钉、飞书、企业微信）原生 Markdown 卡片适配；2) 卡片排版针对排障场景深度优化（一句话结论 ➔ 关键证据 ➔ SRE 命令草稿）；3) 具备失败重试与本地控制台优雅降级渲染 |
| 关键应用点 | 故障诊断完成后的自动化秒级推群、带操作命令的富文本卡片 |

### 2.11 数据敏感信息流式脱敏引擎

| 维度 | 详情 |
|------|------|
| **我们的选择** | **自研基于预编译正则的流式脱敏过滤器 (Data Redactor)** |
| 备选方案 | Presidio-Analyzer (重量级 NLP 模型) |
| 决定性理由 | 1) 运维日志脱敏要求极高吞吐量与极低时延（微秒级），重型 NLP 实体模型开销过大；2) 正则流水线针对运维常见凭据（Bearer Token、Password、AK/SK、私钥）覆盖率达 100%；3) 纯内联替换为 `***REDACTED***`，零外部依赖 |
| 关键应用点 | 所有送入大模型、控制台打印、推送到群聊的日志与配置前置过滤 |

### 2.12 测试框架与故障演练体系

| 维度 | 详情 |
|------|------|
| **我们的选择** | **Pytest 8.3.3 + Pytest-Asyncio 0.24.0 + 离线故障演练 Fixtures** |
| 备选方案 | Unittest、RobotFramework |
| 决定性理由 | 1) 业界事实标准，丰富的断言重写与 Fixture 机制；2) 包含 4 套标准化离线故障演练包（OOMKilled、CrashLoop、DiskPressure、HighLoad），无需任何集群即可在本地 CI/CD 环境一键自测验证 |
| 关键应用点 | 单元测试、契约校验测试、端到端演练回归测试 |

---

## 三、高保真系统架构与模块详设

### 3.1 架构全景图（分层拓扑与事件数据流）

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             输入层 (Ingress & Triggers)                           │
│  ┌──────────────────────────────────────────┐  ┌───────────────────────────────┐ │
│  │   Alertmanager / Prometheus Webhook     │  │   SRE 交互式终端 / Web API    │ │
│  │   POST /webhook/alertmanager (JSON)      │  │   opspilot diagnose / chat    │ │
│  └────────────────────┬─────────────────────┘  └───────────────┬───────────────┘ │
└───────────────────────┼────────────────────────────────────────┼─────────────────┘
                        │                                        │
                        ▼                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                      核心编排层 (Core Diagnostic Engine)                         │
│                                                                                  │
│    ┌────────────────────────────────────────────────────────────────────────┐    │
│    │ 1. 任务归一化与分诊器 (Task Normalizer)                                │    │
│    │    - 提取 target_type (k8s_pod / linux_node), name, namespace, symptoms │    │
│    │    - 初始化 DiagnosticTask (全局唯一 Task ID 溯源)                     │    │
│    └───────────────────────────────────┬────────────────────────────────────┘    │
│                                        ▼                                         │
│    ┌────────────────────────────────────────────────────────────────────────┐    │
│    │ 2. Phase 1: 确定性 SOP 快速拓扑取证 (Deterministic Fast Path, <2s)     │    │
│    │    - K8s 快速取证: describe + logs(--tail=100) + warning events        │    │
│    │    - Linux 主机快速取证: df -h + free -m + dmesg -T + top              │    │
│    │    - 输出第一阶事实证据集 (EvidenceSet)                                │    │
│    └───────────────────────────────────┬────────────────────────────────────┘    │
│                                        ▼                                         │
│    ┌────────────────────────────────────────────────────────────────────────┐    │
│    │ 3. Phase 2: 状态机按需深度探查 (Stateful Deep-Dive & Reasoning)        │    │
│    │    - 状态模型: DiagnosticState (轮次计数、证据池、假设集、收敛标志)    │    │
│    │    - 假设生成 (Hypothesis Generation)                                  │    │
│    │    - 按需调用只读工具箱 (Tool Calling)                                 │    │
│    │    - 硬熔断控制: 最大 3 轮探查循环，防死循环与 Token 膨胀              │    │
│    └───────────────┬───────────────────────────────────────▲────────────────┘    │
│                    │                                       │ (按需调取)          │
│                    ▼                                       │                     │
│    ┌───────────────────────────────────────────────────────┴────────────────┐    │
│    │ 4. 只读安全沙箱与工具箱 (Security Sandbox & Tool Registry)             │    │
│    │    ┌──────────────────────┐  ┌──────────────────────┐                  │    │
│    │    │ K8s 只读探针工具     │  │ Linux 主机白名单探针 │                  │    │
│    │    │ get_pod_events       │  │ inspect_systemd      │                  │    │
│    │    │ get_previous_logs    │  │ check_disk_io        │                  │    │
│    │    └──────────────────────┘  └──────────────────────┘                  │    │
│    │    ┌──────────────────────┐  ┌──────────────────────┐                  │    │
│    │    │ Prometheus PromQL    │  │ Loki 日志流分析      │                  │    │
│    │    │ query_instant/range  │  │ query_loki_stream    │                  │    │
│    │    └──────────────────────┘  └──────────────────────┘                  │    │
│    │    ──────────────────────────────────────────────────                  │    │
│    │    🛡️ 严禁写操作 (Zero-Mutation) + 流式敏感数据脱敏过滤器 (Redactor)   │    │
│    └───────────────────────────────────┬────────────────────────────────────┘    │
│                                        ▼                                         │
│    ┌────────────────────────────────────────────────────────────────────────┐    │
│    │ 5. 结构化 RCA 合成与 SRE 建议引擎 (Synthesis & Report Generation)      │    │
│    │    - 调用 DeepSeek-V3/R1 进行因果链路严谨归纳                          │    │
│    │    - 输出严格 Pydantic 校验的 DiagnosticReport                         │    │
│    │    - 附带 SRE 分级处置方案 (LOW / MEDIUM / HIGH) 与精确可执行命令草稿  │    │
│    └───────────────────────────────────┬────────────────────────────────────┘    │
└────────────────────────────────────────┼─────────────────────────────────────────┘
                                         │
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                         呈现与交付层 (Egress & Presentation)                     │
│  ┌────────────────────────┐  ┌────────────────────────┐  ┌─────────────────────┐ │
│  │ 钉钉 / 飞书 / 企微群    │  │ SRE 终端 CLI           │  │ Web 监控大屏仪表盘  │ │
│  │ 富文本 Markdown 卡片   │  │ Rich 彩色流式排版渲染  │  │ 暗黑 SaaS 控制台    │ │
│  └────────────────────────┘  └────────────────────────┘  └─────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

### 3.2 全部功能模块深度分解（总计 18 个核心模块）

---

#### 模块 01: FastAPI 服务入口与主进程调度
| 属性 | 内容 |
|------|------|
| **模块ID** | M01-APIServer |
| **物理文件路径** | `opspilot/main.py`, `opspilot/api/routes_webhook.py` |
| **核心职责** | 启动 HTTP/Webhook 监听、配置中间件、挂载路由、分发异步诊断任务 |
| **对外API** | `POST /webhook/alertmanager`, `GET /healthz`, `POST /api/v1/diagnose` |
| **内部技术** | FastAPI 0.115.0, Uvicorn, BackgroundTasks 异步分发 |
| **交互流程** | 接收监控 Webhook ➔ 校验签名与格式 ➔ 派发异步排障任务 ➔ 立即返回 200 OK |

**🔧 核心技术栈**:
- `fastapi` 0.115.0 — 异步 Web 框架
- `uvicorn` 0.30.6 — ASGI 高性能服务器
- `pydantic` 2.9.2 — 请求体验证

**🎯 推荐Skills**: `senior-fullstack`、`devops-engineer`

---

#### 模块 02: Alertmanager 告警载荷归一化解析器
| 属性 | 内容 |
|------|------|
| **模块ID** | M02-AlertNormalizer |
| **物理文件路径** | `opspilot/schemas/alert.py`, `opspilot/schemas/task.py` |
| **核心职责** | 解析不同版本 Alertmanager JSON，提取标签、实例、告警名并归一化为 `DiagnosticTask` |
| **对外API** | `AlertmanagerPayload.to_diagnostic_tasks() -> List[DiagnosticTask]` |
| **内部技术** | Pydantic Schema, 启发式实体识别算法（区分 Pod 还是 Node） |
| **交互流程** | 读取 `alerts[].labels` ➔ 检测含 `pod` 键判定为 `k8s_pod`，检测含 `instance/node` 判定为 `linux_node` ➔ 生成带 UUID 的任务实例 |

**数据契约定义**:
```python
class DiagnosticTask(BaseModel):
    task_id: str = Field(..., description="唯一任务跟踪ID")
    source: str = Field(default="alertmanager", description="来源渠道")
    target_type: str = Field(..., description="目标类型: k8s_pod / linux_node")
    target_name: str = Field(..., description="目标实体名称")
    namespace: Optional[str] = Field(None, description="K8s 命名空间")
    alert_name: Optional[str] = Field(None, description="告警规则名称")
    alert_labels: Dict[str, Any] = Field(default_factory=dict)
    symptoms: str = Field(..., description="初始故障症状表象")
```

---

#### 模块 03: 诊断工作流状态机编排器 (Workflow Orchestrator)
| 属性 | 内容 |
|------|------|
| **模块ID** | M03-WorkflowOrchestrator |
| **物理文件路径** | `opspilot/core/workflow.py`, `opspilot/core/state.py` |
| **核心职责** | 状态机流转控制：执行 Phase 1 快速预取 ➔ Phase 2 状态机深挖 ➔ Phase 3 结构化报告合成 |
| **对外API** | `DiagnosticWorkflow.run(task: DiagnosticTask) -> DiagnosticReport` |
| **内部技术** | 两阶段状态流转、轮次计数器、提前收敛判定逻辑、硬熔断控制 |
| **交互流程** | 传入 Task ➔ 初始化 State ➔ 调取 Prefetcher ➔ 判断是否已获取强证据（如 ExitCode 137）➔ 若不足则循环调用 ToolRegistry ➔ 达上限或收敛后调取 LLM ➔ 返回完整报告 |

**状态模型定义**:
```python
class DiagnosticState(BaseModel):
    task: DiagnosticTask
    current_round: int = 0
    max_rounds: int = 3
    evidence_pool: List[EvidenceItem] = Field(default_factory=list)
    hypotheses: List[str] = Field(default_factory=list)
    is_completed: bool = False
    final_report: Optional[DiagnosticReport] = None
```

---

#### 模块 04: Phase 1 确定性 Kubernetes 快速拓扑预取引擎
| 属性 | 内容 |
|------|------|
| **模块ID** | M04-K8sPrefetcher |
| **物理文件路径** | `opspilot/prefetches/k8s_prefetch.py`, `opspilot/prefetches/base.py` |
| **核心职责** | 毫秒级抓取 Pod 运行状态、最近 100 行错误日志、关联 Warning Events、重启原因 |
| **对外API** | `K8sPrefetcher.collect(task: DiagnosticTask) -> List[EvidenceItem]` |
| **内部技术** | `subprocess` + `kubectl describe pod` / `kubectl logs --previous`，5s 超时限制 |
| **交互流程** | 接收 Pod 诊断任务 ➔ 并行获取描述文本与历史崩溃日志 ➔ 经脱敏器清洗 ➔ 打包为 EvidenceItem 注入证据池 |

**🔧 核心技术栈**:
- `kubernetes` 31.0.0
- `kubectl` CLI 适配器
- 流式敏感词脱敏清洗

---

#### 模块 05: Phase 1 确定性 Linux 宿主机快速预取引擎
| 属性 | 内容 |
|------|------|
| **模块ID** | M05-NodePrefetcher |
| **物理文件路径** | `opspilot/prefetches/node_prefetch.py` |
| **核心职责** | 快速抓取 Linux 节点磁盘挂载空间、内存使用、CPU 负载、dmesg 异常 |
| **对外API** | `NodePrefetcher.collect(task: DiagnosticTask) -> List[EvidenceItem]` |
| **内部技术** | `df -h`, `free -m`, `uptime`, `dmesg -T --level=err,warn` |
| **交互流程** | 检查宿主机只读工具 ➔ 顺序执行系统只读探针 ➔ 抽取关键输出行 ➔ 生成证据事实注入证据池 |

---

#### 模块 06: 只读安全沙箱与命令白名单拦截器 (Security Sandbox)
| 属性 | 内容 |
|------|------|
| **模块ID** | M06-SecuritySandbox |
| **物理文件路径** | `opspilot/tools/security.py` |
| **核心职责** | 物理拦截任何非白名单系统命令，杜绝变更操作与 Shell 注入，保障 100% 只读安全 |
| **对外API** | `validate_host_command(cmd_parts: List[str]) -> bool` |
| **内部技术** | 封闭命令白名单集合、`systemctl` 只读子命令限定、拒绝 `shell=True` |
| **交互流程** | 工具执行前解析二进制名 ➔ 校验是否在 ALLOWED_COMMANDS ➔ 若不在立即抛出 `PermissionError` 熔断 |

**白名单定义**:
```python
ALLOWED_COMMAND_BINARIES = {
    "uptime", "free", "df", "ps", "top", "journalctl",
    "systemctl", "dmesg", "ss", "netstat", "vmstat", "iostat", "cat"
}
SYSTEMCTL_ALLOWED_SUBCOMMANDS = {"status", "is-active", "is-failed"}
```

---

#### 模块 07: 数据敏感信息流式脱敏器 (Data Redactor)
| 属性 | 内容 |
|------|------|
| **模块ID** | M07-DataRedactor |
| **物理文件路径** | `opspilot/tools/security.py` |
| **核心职责** | 识别并打码日志与配置中的密码、Bearer Token、AK/SK、私钥凭据 |
| **对外API** | `redact_sensitive_info(content: str) -> str` |
| **内部技术** | 预编译高效正则替换流水线、零额外内存分配 |
| **交互流程** | 原始日志文本进入 ➔ 正则模式扫描 ➔ 匹配项替换为 `***REDACTED***` ➔ 输出安全合规文本 |

---

#### 模块 08: Phase 2 Kubernetes 深度只读探针工具
| 属性 | 内容 |
|------|------|
| **模块ID** | M08-K8sTools |
| **物理文件路径** | `opspilot/tools/k8s_tools.py`, `opspilot/tools/base.py` |
| **核心职责** | 状态机深挖时，按需调取特定 Pod 的详细 Events、Deployment 规格、资源配额限制 |
| **对外API** | `GetPodEventsTool.execute(namespace: str, pod_name: str) -> str` |
| **内部技术** | OpenAI Tool Definition 格式导出、field-selector 事件过滤 |
| **交互流程** | LLM 产生“查看该 Pod 事件详情”决策 ➔ 触发工具执行 ➔ 返回精简事件摘要 |

---

#### 模块 09: Phase 2 Linux 宿主机深度只读探针工具
| 属性 | 内容 |
|------|------|
| **模块ID** | M09-HostTools |
| **物理文件路径** | `opspilot/tools/host_tools.py` |
| **核心职责** | 检查指定 systemd 单元状态（`systemctl status`）、端口占用（`ss -tulpn`）、磁盘使用明细 |
| **对外API** | `InspectSystemdServiceTool.execute(service_name: str) -> str` |
| **内部技术** | 参数化 `subprocess.run` + 严格沙箱白名单二次复核 |
| **交互流程** | LLM 怀疑 Nginx 或 Docker 服务僵死 ➔ 调用工具 ➔ 返回服务 Active 状态及最近日志 |

---

#### 模块 10: Phase 2 Prometheus PromQL 时序指标探针
| 属性 | 内容 |
|------|------|
| **模块ID** | M10-MetricTools |
| **物理文件路径** | `opspilot/tools/metric_tools.py` |
| **核心职责** | 执行 PromQL 即时查询，获取 CPU 使用率、内存 WorkingSet、网络吞吐等时序度量 |
| **对外API** | `QueryPrometheusTool.execute(query: str) -> str` |
| **内部技术** | HTTPX GET 查询、时序结果标量压缩提取、超时保护 |
| **交互流程** | 接收 PromQL 表达式 ➔ 发起 HTTP 请求 ➔ 压缩提取时间戳与数值 ➔ 转化为单行证据文本 |

---

#### 模块 11: Phase 2 Loki 日志流分析探针
| 属性 | 内容 |
|------|------|
| **模块ID** | M11-LogTools |
| **物理文件路径** | `opspilot/tools/log_tools.py` |
| **核心职责** | 跨应用定向查询指定时间范围内的错误堆栈与关键词出现频次 |
| **对外API** | `QueryLokiLogsTool.execute(logql: str, limit: int = 100) -> str` |
| **内部技术** | Loki LogQL HTTP API、按行流式截断、错误模式聚类 |
| **交互流程** | 接收 LogQL 查询语句 ➔ 限制单次最多返回 100 行 ➔ 过滤空白行并脱敏 ➔ 返回聚类日志 |

---

#### 模块 12: 大模型 RCA 因果推理引擎与 Prompt 链
| 属性 | 内容 |
|------|------|
| **模块ID** | M12-LLMReasoner |
| **物理文件路径** | `opspilot/core/llm.py`, `opspilot/core/prompt_templates.py` |
| **核心职责** | 组装证据上下文，基于专家 System Prompt 引导 LLM 进行因果推导，严格输出 JSON |
| **对外API** | `LLMClient.synthesize_rca(task_id, target, symptoms, evidence_summary) -> DiagnosticReport` |
| **内部技术** | OpenAI SDK 兼容协议、JSON Object Response Format、降级静态报告兜底 |
| **交互流程** | 组装 Prompt ➔ 调用 DeepSeek/Qwen API ➔ JSON 格式校验 ➔ 实例化 DiagnosticReport ➔ 若 API 故障转静态兜底 |

**核心提示词设计**:
```text
你是一名资深的 SRE 和云原生运维专家。
你的任务是根据给定的【故障表象】以及【已收集的客观证据事实】，推导故障的根本原因（RCA），并给出分级处置建议。
原则：
1. 严禁凭空臆造。所有根因推导必须能在证据链（Evidence Chain）中找到对应事实支撑。
2. 建议必须具有明确的安全风险等级（LOW / MEDIUM / HIGH），并提供供人工审查执行的具体命令草稿。
3. 输出必须是合法严格的 JSON 格式，完全符合 DiagnosticReport 模式。
```

---

#### 模块 13: 结构化根因报告与处置建议模型 (Schemas)
| 属性 | 内容 |
|------|------|
| **模块ID** | M13-ReportSchema |
| **物理文件路径** | `opspilot/schemas/report.py` |
| **核心职责** | 定义标准 RCA 报告结构，包含证据链、根因结论、处置建议动作及耗时统计 |
| **对外API** | `DiagnosticReport`, `EvidenceItem`, `RemediationAction` |
| **内部技术** | Pydantic v2 强校验模型、置信度浮点数约束、枚举分级 |
| **交互流程** | 供 LLMClient 与各呈现模块作为强契约输入输出 |

**结构化报告定义**:
```python
class RemediationAction(BaseModel):
    title: str = Field(..., description="处置动作简述")
    risk_level: str = Field(..., description="风险等级: LOW / MEDIUM / HIGH")
    command_draft: Optional[str] = Field(None, description="供人工复制执行的命令草稿")
    explanation: str = Field(..., description="操作目的与影响说明")

class DiagnosticReport(BaseModel):
    task_id: str
    target: str
    status: str = Field(..., description="排查状态: SUCCESS / PARTIAL_FAILURE / UNRESOLVED")
    fault_summary: str = Field(..., description="一句话故障定位摘要")
    root_cause: str = Field(..., description="定位出的核心根因结论")
    evidence_chain: List[EvidenceItem] = Field(default_factory=list)
    remediation_actions: List[RemediationAction] = Field(default_factory=list)
    duration_seconds: float = Field(...)
```

---

#### 模块 14: 钉钉/飞书/企业微信机器人通知推送器
| 属性 | 内容 |
|------|------|
| **模块ID** | M14-WebhookNotifier |
| **物理文件路径** | `opspilot/notifiers/dingtalk.py`, `opspilot/notifiers/base.py` |
| **核心职责** | 将结构化 RCA 报告渲染为精美的富文本 Markdown 卡片，秒级推送到告警群聊 |
| **对外API** | `DingTalkNotifier.notify(report: DiagnosticReport) -> bool` |
| **内部技术** | HTTPX POST 异步调用群机器人 Webhook、Markdown 模板格式化 |
| **交互流程** | 报告生成 ➔ 模板引擎排版（注入目标、根因、高光证据、命令代码块）➔ 推送到钉钉/飞书群 |

---

#### 模块 15: Rich 控制台彩色排版渲染器
| 属性 | 内容 |
|------|------|
| **模块ID** | M15-ConsoleNotifier |
| **物理文件路径** | `opspilot/notifiers/console.py` |
| **核心职责** | SRE 在终端中运行时的富文本展示，以 Panel、颜色高亮与表格展示排障结论 |
| **对外API** | `ConsoleNotifier.notify(report: DiagnosticReport) -> bool` |
| **内部技术** | Rich 13.8.1 `Console`, `Panel`, `Table` |
| **交互流程** | 接收报告 ➔ 组织终端彩色视图 ➔ 打印至 stdout |

---

#### 模块 16: Typer SRE 命令行交互客户端 (CLI)
| 属性 | 内容 |
|------|------|
| **模块ID** | M16-CLIApp |
| **物理文件路径** | `opspilot/cli/main.py` |
| **核心职责** | 提供命令行交互界面，支持手动指定目标排障与离线模拟演练 |
| **对外API** | `opspilot diagnose --type k8s_pod --name <pod>`, `opspilot run-mock` |
| **内部技术** | Typer 0.12.5, CLI 参数自动解析, UUID 追踪 |
| **交互流程** | SRE 输入 CLI 指令 ➔ 解析目标参数 ➔ 启动 Workflow ➔ 终端彩色实时输出 |

---

#### 模块 17: Web 控制台与大屏看板 (UI Dashboard)
| 属性 | 内容 |
|------|------|
| **模块ID** | M17-WebDashboard |
| **物理文件路径** | `ui/index.html` |
| **核心职责** | 提供暗黑极客风格的前端可视化面板，包含指标卡、6格报告库、AI 排障器、热力图、环形图 |
| **对外API** | 浏览器直接打开或由 FastAPI 托管静态页面 |
| **内部技术** | Tailwind CSS, Plus Jakarta Sans 字体, 原生微交互, 故障场景切换器 |
| **交互流程** | 用户在界面点击场景（OOM/磁盘满/CrashLoop）➔ 实时刷新工作区数据 ➔ 支持一键复制处置命令 |

---

#### 模块 18: 离线故障演练与 Mock 仿真器
| 属性 | 内容 |
|------|------|
| **模块ID** | M18-MockDrillSimulator |
| **物理文件路径** | `tests/test_e2e_scenarios.py` |
| **核心职责** | 内置 4 套典型故障测试用例，无需真实集群在本地即可 100% 验证 RCA 全链路正确性 |
| **对外API** | `pytest tests/test_e2e_scenarios.py -v` |
| **内部技术** | Pytest 测试夹具、典型故障场景还原（OOM 137、磁盘 98%、Config 缺失、CPU Throttling） |
| **交互流程** | CI/CD 流程执行测试 ➔ 实例化模拟任务 ➔ 触发 Workflow ➔ 断言根因与处置动作匹配度 |

---

## 四、项目工程化终极指南

### 4.1 完整项目目录树

```text
opspilot/
├── .env.example                          # 环境变量配置文件模板
├── pyproject.toml                        # 现代 Python 项目依赖与打包规范
├── requirements.txt                      # 生产依赖锁定列表
├── README.md                             # 快速入门与架构说明
├── Dockerfile                            # 容器化镜像构建文件
├── docker-compose.yml                    # 本地快速拉起服务编排
│
├── ui/                                   # 前端可视化控制台
│   └── index.html                        # 像素级暗黑 SaaS 风格交互式排障大屏
│
├── opspilot/                             # 核心应用源码
│   ├── __init__.py                       # 模块版本声明 (v0.1.0)
│   ├── main.py                           # FastAPI 生产服务启动入口
│   ├── config.py                         # 基于 Pydantic-Settings 的配置加载中心
│   │
│   ├── schemas/                          # 全局数据契约与数据模型
│   │   ├── __init__.py
│   │   ├── task.py                       # DiagnosticTask 统一任务契约
│   │   ├── report.py                     # DiagnosticReport 结构化 RCA 报告模型
│   │   └── alert.py                      # Alertmanager 告警载荷模型与解析器
│   │
│   ├── core/                             # Agent 核心大脑与状态机
│   │   ├── __init__.py
│   │   ├── state.py                      # 诊断状态模型 (DiagnosticState)
│   │   ├── workflow.py                   # 状态机编排器 (两阶段调度与熔断保护)
│   │   ├── prompt_templates.py           # SRE RCA 专家系统提示词与 Few-Shot
│   │   └── llm.py                        # 兼容 OpenAI 标准的大模型客户端适配器
│   │
│   ├── prefetches/                       # Phase 1: 确定性 SOP 快速拓扑抓取
│   │   ├── __init__.py
│   │   ├── base.py                       # 抽象 Prefetcher 基类定义
│   │   ├── k8s_prefetch.py               # K8s Pod 状态/日志/Events 预拉取
│   │   └── node_prefetch.py              # Linux 宿主机 CPU/内存/磁盘/dmesg 预拉取
│   │
│   ├── tools/                            # Phase 2: 只读探针工具箱与安全沙箱
│   │   ├── __init__.py
│   │   ├── base.py                       # 工具基类与 OpenAI Function 协议转换
│   │   ├── security.py                   # 命令白名单拦截器与流式敏感数据脱敏器
│   │   ├── k8s_tools.py                  # K8s 只读诊断工具 (Events/Logs/YAML)
│   │   ├── host_tools.py                 # Linux 主机工具 (systemd/端口/IO)
│   │   └── metric_tools.py               # Prometheus PromQL 时序度量工具
│   │
│   ├── notifiers/                        # 结果交付与多渠道通知
│   │   ├── __init__.py
│   │   ├── base.py                       # 通知器抽象基类
│   │   ├── console.py                    # Rich 终端彩色排版输出器
│   │   └── dingtalk.py                   # 钉钉/飞书富文本 Markdown 卡片生成器
│   │
│   ├── api/                              # Web API 路由层
│   │   ├── __init__.py
│   │   └── routes_webhook.py             # 告警 Webhook 接收与派发路由
│   │
│   └── cli/                              # SRE 命令行客户端
│       ├── __init__.py
│       └── main.py                       # opspilot 终端命令入口
│
└── tests/                                # 自动化测试套件与离线演练
    ├── test_config.py                    # 配置加载单元测试
    ├── test_schemas.py                   # 告警与报告数据契约测试
    ├── test_security.py                  # 沙箱白名单与敏感脱敏过滤器测试
    ├── test_prefetch.py                  # Phase 1 快速预取 SOP 测试
    ├── test_tools.py                     # Phase 2 只读探针工具测试
    ├── test_llm.py                       # LLM 客户端与结构化格式化测试
    ├── test_workflow.py                  # 状态机端到端流转与熔断测试
    ├── test_notifiers.py                 # 终端与卡片渲染测试
    ├── test_api_and_cli.py               # FastAPI Webhook 与 CLI 测试
    └── test_e2e_scenarios.py             # 4 组经典离线故障模拟演练
```

---

### 4.2 `pyproject.toml` 完整配置

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "opspilot"
version = "0.1.0"
description = "OpsPilot AI: Production-Ready AIOps RCA Diagnostic Agent"
readme = "README.md"
requires-python = ">=3.10"
license = { text = "MIT" }
authors = [
    { name = "OpsPilot Team", email = "sre@opspilot.ai" }
]
keywords = ["aiops", "sre", "kubernetes", "agent", "rca", "observability"]
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn>=0.30.6",
    "pydantic>=2.9.2",
    "pydantic-settings>=2.5.2",
    "httpx>=0.27.2",
    "typer>=0.12.5",
    "rich>=13.8.1",
    "paramiko>=3.5.0",
]

[project.optional-dependencies]
test = [
    "pytest>=8.3.3",
    "pytest-asyncio>=0.24.0",
]

[project.scripts]
opspilot = "opspilot.cli.main:app"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

---

### 4.3 环境变量配置文件 (`.env.example`)

```env
# ==============================================================================
# OpsPilot AI - 核心环境变量配置
# ==============================================================================

# ---- 大模型服务配置 (默认采用 DeepSeek-V3，兼容 OpenAI 协议) ----
LLM_API_KEY=sk-your-actual-api-key-here
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
LLM_TEMPERATURE=0.1

# 可选：切换为本地离线 Ollama 运行
# LLM_BASE_URL=http://localhost:11434/v1
# LLM_MODEL=qwen2.5:14b
# LLM_API_KEY=ollama

# ---- 状态机与安全控制参数 ----
MAX_DEEPDIVE_ROUNDS=3
READ_ONLY_MODE=true
LOG_TAIL_LINES=100

# ---- 可观测性数据源接入配置 (选填) ----
PROMETHEUS_URL=http://prometheus-k8s.monitoring.svc:9090
LOKI_URL=http://loki.monitoring.svc:3100
KUBECONFIG_PATH=~/.kube/config

# ---- Webhook 与服务端口配置 ----
API_HOST=0.0.0.0
API_PORT=8080

# ---- 通知渠道配置 (选填) ----
DINGTALK_WEBHOOK_URL=https://oapi.dingtalk.com/robot/send?access_token=your-token
FEISHU_WEBHOOK_URL=https://open.feishu.cn/open-apis/bot/v2/hook/your-token
```

---

### 4.4 从零启动的“傻瓜式”运维指南

#### 步骤 1：准备 Python 环境与安装依赖
```bash
# 建议使用 Python 3.10 或更高版本
python -m venv .venv

# Linux / macOS 激活环境
source .venv/bin/activate
# Windows PowerShell 激活环境
# .venv\Scripts\Activate.ps1

# 安装依赖
pip install -e ".[test]"
```

#### 步骤 2：配置环境变量
```bash
cp .env.example .env
# 编辑 .env 文件，填入你的大模型 API 密钥（如 DeepSeek API Key）
```

#### 步骤 3：一键运行自动化测试与 4 套离线故障演练
```bash
# 执行完整测试套件，自动运行 4 大典型故障（OOM、磁盘满、配置缺失、高负载）
pytest tests/ -v
```

#### 步骤 4：启动 Webhook 自动化服务
```bash
# 启动 FastAPI 服务，监听 8080 端口
python -m uvicorn opspilot.main:app --host 0.0.0.0 --port 8080 --reload
```
服务启动后：
- 健康检查：`http://localhost:8080/healthz`
- 接收告警 Webhook 接口：`POST http://localhost:8080/webhook/alertmanager`
- 交互式 UI 大屏控制台：直接在浏览器中打开 `ui/index.html` 即可体验。

#### 步骤 5：使用 SRE 终端命令行交互排查
```bash
# 示例 1: 针对指定 Pod 发起排障
opspilot diagnose --type k8s_pod --name order-service-7f654b --namespace prod --symptoms "Pod status CrashLoopBackOff"

# 示例 2: 针对指定主机节点发起排障
opspilot diagnose --type linux_node --name 192.168.1.101 --symptoms "Host DiskSpaceFillingUp /dev/vda1 > 95%"
```

---

## 五、关键设计决策与安全模型

### 5.1 数据流向与生命周期图

```text
[Prometheus 告警触发] ➔ Alertmanager
                           ↓ Webhook POST /webhook/alertmanager
                     M01 FastAPI 异步路由接收
                           ↓
                     M02 告警归一化为 DiagnosticTask
                           ↓
                     M03 Workflow 状态机激活
                           ↓
         ┌─────────────────┴─────────────────┐
         ▼ (k8s_pod)                         ▼ (linux_node)
   M04 K8s 快速取证                    M05 主机快速取证
   (describe / logs / events)          (df / free / dmesg)
         └─────────────────┬─────────────────┘
                           ↓
                     M07 敏感数据流式脱敏 (Redactor)
                           ↓
                     存入 DiagnosticState.evidence_pool
                           ↓
                     M03 状态机判定（是否已命中强事实证据？）
                           ├─ 是 ➔ 直接收敛
                           └─ 否 ➔ 调用 M08-M11 深度探查 (最多 3 轮)
                                     ↓
                     M12 LLM 专家因果推理
                           ↓
                     M13 生成结构化 DiagnosticReport (根因 + 分级命令)
                           ↓
         ┌─────────────────┴─────────────────┐
         ▼                                   ▼
   M14 钉钉/飞书群卡片推送             M15 终端控制台彩色展示
```

### 5.2 绝对只读安全沙箱模型 (Zero-Mutation Guardrail)

```text
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             SRE / LLM 发起排障指令                               │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                       只读安全沙箱校验器 (Security Sandbox)                      │
│                                                                                  │
│   1. 命令参数化解析 (禁止拼接, 杜绝 Shell 注入)                                    │
│   2. 严格白名单比对: cmd[0] 必须在 ALLOWED_COMMAND_BINARIES 中                  │
│   3. 危险指令熔断拦截:                                                           │
│      - 发现 "rm", "reboot", "shutdown", "dd", "mkfs" ➔ 立即抛出 PermissionError  │
│      - 发现 "systemctl restart/stop" ➔ 物理拦截 (仅放行 status)                  │
│   4. K8s RBAC 限制:                                                              │
│      - ServiceAccount 仅绑定只读 ClusterRole (verbs: ["get", "list", "watch"])  │
└────────────────────────────────────────┬─────────────────────────────────────────┘
                                         │ 放行安全只读查询
                                         ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                      系统实际调用 (只读抓取现场数据)                             │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 熔断降级与容错兜底策略
1. **数据源网络超时兜底**：Prometheus / Loki 单次查询设置 8 秒硬超时。若超时失联，状态机自动将该数据源标记为不可用，依靠已获取的 K8s Events 和日志继续分析，并在报告中明确声明。
2. **大模型 API 限流与异常兜底**：若大模型网络抖动或限流，系统自动触发 **Fallback SOP 静态报告引擎**，直接将 Phase 1 采集到的原始错误日志与系统占用数据格式化推送给 SRE，确保故障现场一手数据永不丢失。
3. **探查深度硬熔断**：LangGraph 状态机严格限定探查深度上限为 3 次循环，无论证据是否充分，达到上限强制收敛输出，杜绝死循环和成本失控。

---

> **结语**：本技术文档严格按照工业级高可用设计标准编写，涵盖需求分析、技术选型决策矩阵、18 个核心模块详设、完整工程化指南与安全模型。为后续的工程实现提供了严密的架构蓝图。
