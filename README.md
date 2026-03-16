# SRE Agent 中文说明

这是一个面向单机 Linux 服务器的自主运维 Agent，当前版本聚焦你的目标场景：

- 腾讯云 CVM
- 2 核 2G 规格服务器
- Docker 部署的 Java 应用
- Webhook 告警通知
- 可控范围内的低风险自动处置

当前版本的重点不是做一个大而全的 AIOps 平台，而是先把一个能在真实服务器上稳定跑起来、能发现问题、能降级分析、能输出诊断结果的 MVP 做扎实。

## 当前架构

项目现在同时保留两条运行路径：

- `legacy` 路径：沿用现有 detector 的逐目标巡检逻辑
- `autonomous` 路径：使用 ReAct + LangGraph 风格的自主诊断框架

默认建议在服务器上直接启用 autonomous 模式，用真实输入来源先跑一轮验证当前设计。

## 当前能力

### 第一层：主机层巡检

- CPU 压力检测
- 可用内存过低检测
- 磁盘使用率过高检测

### 第二层：Docker 层巡检

- 容器未运行检测
- 容器重启次数过高检测
- 容器 `OOMKilled=true` 检测
- 容器标准输出日志采集

### 第三层：Java 层巡检

- `ERROR` 日志突增检测
- JVM OOM 关键字检测
- Full GC 关键字检测
- 异常时抓取线程栈

### 第四层：业务层巡检

- workflow 失败率升高
- workflow 长时间 `running` 卡住
- Token 消耗异常
- Tool 调用失败率升高

### 自主诊断框架

- ReAct 风格工具调用闭环
- 可切换的 autonomous 诊断入口
- 周期级 incident 聚合与粗粒度关联
- 真实 tool registry
- 代码库检索
- 历史 incident 召回
- 输入来源可用性建模与降级策略

## 输入来源与降级策略

这版 Agent 不再假设所有输入都能拿到，而是显式记录每一类输入来源当前是否：

- `available`
- `degraded`
- `missing`
- `unsupported`

Agent 会按照来源类别动态选取当前可用的输入，而不是在某一条链路缺失时直接失效。

### 当前已接入的主要输入来源

- `/proc/stat`
- `/proc/meminfo`
- `docker inspect`
- `docker logs`
- `jstack` / `jcmd` / `SIGQUIT` 线程栈诊断
- `Prometheus API`
- `incidents.jsonl`
- Java 源码目录检索

### 当前已建模但尚未接入的来源

- `docker stats`
- `jstat -gc`
- GC 日志文件
- 挂载到宿主机的应用日志文件
- `/actuator/health`
- `/actuator/metrics`
- Alertmanager
- 业务数据库查询
- Grafana 截图
- ELK
- Jaeger

这意味着你现在上服务器验证时，Agent 可以明确告诉你：

- 哪些来源已经可用
- 哪些来源会降级
- 哪些来源当前根本没接

## 项目目录

关键目录如下：

- `src/sre_agent/monitor/`
- `src/sre_agent/detectors/`
- `src/sre_agent/tools/`
- `src/sre_agent/graph/`
- `src/sre_agent/deployment/`
- `src/sre_agent/notify/`
- `src/sre_agent/storage/`
- `deploy/`
- `docs/`

关键入口文件：

- `src/sre_agent/monitor/service.py`
- `src/sre_agent/cli/main.py`
- `src/sre_agent/run.py`
- `src/sre_agent/core/settings.py`

## Linux 服务器部署前提

### 必备条件

- Linux 服务器
- Python 3.13
- Docker CLI 可用
- 当前用户能够访问 Docker daemon
- 至少一个正在运行的 Java 容器

### 推荐条件

- Prometheus 已部署并可访问
- Java 源码目录已同步或挂载到服务器
- 应用日志已输出到容器标准输出
- Webhook 已配置

## 快速开始

### 1. 克隆代码

```bash
git clone <你的仓库地址>
cd sre-agent
```

### 2. 创建虚拟环境

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. 安装项目

```bash
pip install --upgrade pip
pip install -e .
```

### 4. 准备配置

```bash
cp deploy/examples/tencent-cloud-cvm-2c2g.env .env
```

最少要修改这些项：

- `APP_CONTAINER_NAME` 或 `APP_CONTAINER_NAMES`
- `WEBHOOK_URL`
- `OPENAI_API_KEY`
- `CODEBASE_PATH` 或 `REPOSITORY_PATH`
- `INCIDENT_STORE_PATH`
- `PROMETHEUS_BASE_URL`，如果你已经部署了 Prometheus

## 部署前检查

在真正启动 monitor 之前，先运行部署就绪检查：

```bash
PYTHONPATH=src python -m sre_agent.cli.main check-deploy
```

如果你想拿到结构化输出：

```bash
PYTHONPATH=src python -m sre_agent.cli.main check-deploy --json
```

这个命令会直接告诉你：

- 当前是不是 Linux 服务器环境
- `/proc` 指标文件是否可用
- Docker CLI 和 Docker daemon 是否可用
- 配置的容器是否能被 Agent 看到
- 当前 autonomous 模式是否启用
- 哪些输入来源可用，哪些会降级或缺失

## 本地单次验证命令

### 单次诊断

```bash
PYTHONPATH=src python -m sre_agent.run
```

### 单次巡检

```bash
PYTHONPATH=src python -m sre_agent.cli.main monitor --once
```

### 强制启用自主模式单次巡检

```bash
PYTHONPATH=src python -m sre_agent.cli.main monitor --once --autonomous
```

### 单次自主诊断

```bash
PYTHONPATH=src python -m sre_agent.cli.main diagnose --autonomous
```

### 测试通知

```bash
PYTHONPATH=src python -m sre_agent.cli.main test-notify --message "sre agent test"
```

## 服务器部署流程

### 1. 上传代码到服务器

```bash
mkdir -p /opt/sre-agent
cd /opt/sre-agent
git clone <你的仓库地址> .
```

### 2. 执行安装脚本

```bash
cd /opt/sre-agent
bash deploy/install_server.sh
```

安装脚本会自动完成：

- 创建 `.venv`
- 安装项目
- 初始化 `/etc/sre-agent.env`
- 安装 `systemd` 服务
- 执行 `systemctl daemon-reload`

### 3. 修改服务器配置

```bash
vim /etc/sre-agent.env
```

示例模板来自：

- `deploy/examples/tencent-cloud-cvm-2c2g.env`

### 4. 执行服务器自检

```bash
cd /opt/sre-agent
bash deploy/check_server.sh
```

这个脚本会检查：

- Python 是否可用
- Docker 是否可用
- `/etc/sre-agent.env` 是否存在
- 配置的容器是否可见
- deployment readiness 报告是否通过
- 单次诊断是否能跑通

### 5. 启动服务

```bash
systemctl enable sre-agent
systemctl start sre-agent
systemctl status sre-agent
journalctl -u sre-agent -f
```

## 推荐服务器配置

下面这些配置对你当前目标场景最重要：

### 基本运行

- `GRAPH_ENABLE_AUTONOMOUS_LOOP=true`
- `APP_CONTAINER_NAME` 或 `APP_CONTAINER_NAMES`
- `OPENAI_API_KEY`
- `MODEL`
- `OPENAI_BASE_URL`

### 证据来源

- `CODEBASE_PATH`
- `PROMETHEUS_BASE_URL`
- `INCIDENT_STORE_PATH`

### 主机阈值

- `CHECK_INTERVAL_SECONDS`
- `HOST_DISK_PATH`
- `CPU_PERCENT_THRESHOLD`
- `MEMORY_AVAILABLE_THRESHOLD_MB`
- `DISK_THRESHOLD_PERCENT`
- `LOAD_THRESHOLD_PER_CORE`

### 容器与 JVM

- `APP_LOG_SINCE_SECONDS`
- `CONTAINER_RESTART_THRESHOLD`
- `ERROR_BURST_THRESHOLD`
- `FULL_GC_THRESHOLD`
- `JAVA_DIAG_MODE`

### 业务阈值

- `WORKFLOW_TIMEOUT_SECONDS`
- `WORKFLOW_FAILURE_RATE_THRESHOLD`
- `TOKEN_ANOMALY_THRESHOLD`
- `TOOL_FAILURE_RATE_THRESHOLD`

### 通知

- `WEBHOOK_URL`
- `WEBHOOK_PROVIDER`
- `WEBHOOK_TIMEOUT_SECONDS`

### 自动处置

- `AUTO_REMEDIATE`
- `LOG_RETENTION_DAYS`
- `LOG_CLEAN_PATHS`
- `WORKFLOW_CANCEL_URL`
- `WORKFLOW_CANCEL_TOKEN`

## 当前适合你的验证方式

如果你现在是第一次把它部署到服务器，建议按这个顺序验证：

1. `check-deploy`
2. `diagnose --autonomous`
3. `monitor --once --autonomous`
4. 看 `journalctl -u sre-agent -f`

这样你会很快看清：

- 当前设计是否能拿到足够输入
- 哪些输入还没接进来
- 当前的降级链是否符合你的预期

## 当前限制

当前版本已经能用于服务器首轮验证，但还存在这些限制：

- `/actuator/health` 与 `/actuator/metrics` 还未接入 autonomous 路径
- `docker stats` 还未接入
- `jstat -gc` 与 GC 日志文件还未接入
- 业务数据库查询还未接入
- Grafana、ELK、Jaeger 仅建模，未实现
- RAG 向量检索、长期记忆、Langfuse、RAGAS 还未完成

## 一句话总结

这版 README 对应的是一个可以直接上 Linux 服务器验证的版本。它的核心特点不是“所有输入都已齐备”，而是“输入不齐时也能明确降级并继续分析”。
