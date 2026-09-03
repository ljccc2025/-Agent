# M02 模块（工业级告警归一化解析、指纹去重与风暴抑制）实现计划

> **面向 AI 代理的工作者：** 必需子技能：使用 superpowers:subagent-driven-development（推荐）或 superpowers:executing-plans 逐任务实现此计划。步骤使用复选框（`- [ ]`）语法来跟踪进度。

**目标：** 构建 OpsPilot 的核心告警归一化与防抖去重引擎（M02-AlertNormalizer），提供确定性 SHA256 告警指纹生成、基于滑动时间窗口的防抖去重缓存、突发告警风暴故障域聚合抑制，以及支持 Alertmanager 和 Grafana Alerting 的多监控源适配器。

**架构：** 在 `opspilot/normalizer/` 包下实现核心去重、节流与适配器。通过线程安全内存滑动窗口实现高效 TTL 去重，结合 Pydantic v2 强类型校验完成异构告警载荷到 `DiagnosticTask` 的转换，并在 `opspilot/api/routes_webhook.py` 无缝挂载。

---

## 任务拆分与执行清单

### 任务 1：配置扩充与 DiagnosticTask 契约增强
- **目标：** 在 `opspilot/config.py` 中增加告警去重窗口与风暴阈值配置项；在 `opspilot/schemas/task.py` 中为 `DiagnosticTask` 增加 `fingerprint`, `duplicate_count`, `is_storm_aggregated` 字段；在 `opspilot/schemas/alert.py` 扩展响应模型。
- **文件：**
  - 修改：`opspilot/config.py`
  - 修改：`opspilot/schemas/task.py`
  - 修改：`opspilot/schemas/alert.py`
  - 测试：`tests/test_m02_schemas.py`
- [x] 步骤 1：编写失败测试（RED）
- [x] 步骤 2：更新 config 与 schemas 实现字段增强（GREEN）
- [x] 步骤 3：Git 提交

### 任务 2：确定性 SHA256 告警指纹生成器 (`opspilot/normalizer/fingerprint.py`)
- **目标：** 实现根据告警标签字典（排序防抖）、目标类型、目标名称、命名空间生成确定性的 SHA256 指纹。
- **文件：**
  - 创建：`opspilot/normalizer/__init__.py`
  - 创建：`opspilot/normalizer/fingerprint.py`
  - 测试：`tests/test_fingerprint.py`
- [x] 步骤 1：编写指纹幂等性与唯一性测试（RED）
- [x] 步骤 2：实现 `generate_alert_fingerprint`（GREEN）
- [x] 步骤 3：Git 提交

### 任务 3：线程安全 TTL 滑动窗口告警防抖去重缓存 (`opspilot/normalizer/deduplicator.py`)
- **目标：** 实现内存中的告警去重器 `AlertDeduplicator`，支持可配置的 TTL 窗口、去重拦截、频次递增、并发保护与过期淘汰。
- **文件：**
  - 创建：`opspilot/normalizer/deduplicator.py`
  - 测试：`tests/test_deduplicator.py`
- [x] 步骤 1：编写去重器单元测试（首次放行、窗口期去重、TTL 过期重新放行、并发安全）（RED）
- [x] 步骤 2：实现 `AlertDeduplicator`（GREEN）
- [x] 步骤 3：Git 提交

### 任务 4：告警风暴突发聚合与限流抑制器 (`opspilot/normalizer/throttler.py`)
- **目标：** 实现 `AlertStormThrottler`，当短时间同一故障域告警激增时触发风暴保护，自动聚合并标记。
- **文件：**
  - 创建：`opspilot/normalizer/throttler.py`
  - 测试：`tests/test_throttler.py`
- [x] 步骤 1：编写风暴抑制测试（RED）
- [x] 步骤 2：实现 `AlertStormThrottler`（GREEN）
- [x] 步骤 3：Git 提交

### 任务 5：多监控平台适配器与通用 Normalizer (`opspilot/normalizer/adapters.py`)
- **目标：** 实现 `AlertmanagerAdapter`、`GrafanaAlertAdapter` 与 `NormalizerRegistry`，自动推断异构监控源并归一化为 `DiagnosticTask`。
- **文件：**
  - 创建：`opspilot/normalizer/adapters.py`
  - 测试：`tests/test_adapters.py`
- [ ] 步骤 1：编写异构监控源解析测试（RED）
- [ ] 步骤 2：实现多适配器与注册表（GREEN）
- [ ] 步骤 3：Git 提交

### 任务 6：Webhook 路由升级与 M02 端到端集成测试
- **目标：** 在 `opspilot/api/routes_webhook.py` 接入去重器与适配器；新增 `/webhook/grafana`；编写端到端集成测试并在虚拟机上部署验证。
- **文件：**
  - 修改：`opspilot/api/routes_webhook.py`
  - 创建：`tests/test_m02_integration.py`
- [ ] 步骤 1：编写端到端集成测试（RED）
- [ ] 步骤 2：升级 Webhook 路由接入去重流程（GREEN）
- [ ] 步骤 3：全量回归 `pytest tests/ -v`
- [ ] 步骤 4：虚拟机同步、编译、测试与 Git 提交
