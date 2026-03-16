# SRE Agent 中文说明

这是一个面向单机 Linux 服务器的轻量运维 Agent，当前版本专门针对你的目标场景进行了收敛：

- 腾讯云 CVM
- 2 核 2G 规格服务器
- Docker 部署的 Java 应用
- Webhook 告警通知
- 安全边界内的低风险自动处置

当前版本不是一个追求大而全的 AIOps 平台，而是一个可以先在你的服务器上稳定跑起来的 MVP 运维值班员。

它会定时巡检主机、容器、JVM 和业务日志，发现异常后自动采集证据、生成根因报告、发送通知，并在你开启开关后执行少量白名单处置动作。

## 当前能力

### 第一层：主机层巡检

- CPU 压力检测
- 可用内存过低检测
- 磁盘使用率过高检测

### 第二层：Docker 层巡检

- 容器未运行检测
- 容器重启次数过高检测
- 容器 `OOMKilled=true` 检测

### 第三层：Java 层巡检

- `ERROR` 日志突增检测
- JVM OOM 关键字检测
- Full GC 关键字检测
- 异常时抓取线程栈

### 第四层：业务层巡检

- workflow 失败率升高
- workflow 长时间 running 卡住
- Token 消耗异常
- Tool 调用失败率升高

## 异常发现后的处理流程

1. 探测器发现异常
2. 采集主机、容器、日志、JVM 证据
3. 生成结构化 incident
4. 输出根因诊断报告
5. 本地落盘保存 incident
6. 通过 Webhook 发送通知
7. 如启用自动处置，则执行白名单动作

## 当前主链路包含的模块

- 本机巡检
- Docker 检测
- Java 日志分析
- 结构化业务日志分析
- Webhook 通知
- incident 落盘
- 安全白名单处置
- CLI 命令行入口

## 已删除的旧能力

这次改造已经把原项目里当前不再需要的旧代码从主仓库里清掉了，主要包括：

- AWS ECS 部署链路
- CloudWatch 工具链路
- Slack MCP 链路
- GitHub MCP 链路
- 旧的交互式 CLI 向导
- 旧的评测代码入口

现在仓库主路径只保留当前单机运维 Agent 所需内容。

## 项目目录说明

当前最关键的目录如下：

- `src/sre_agent/monitor/`
- `src/sre_agent/detectors/`
- `src/sre_agent/actions/`
- `src/sre_agent/notify/`
- `src/sre_agent/storage/`
- `deploy/`
- `docs/`

关键入口文件：

- `src/sre_agent/monitor/service.py`
- `src/sre_agent/cli/main.py`
- `src/sre_agent/run.py`
- `src/sre_agent/core/settings.py`

## 本地开发启动

### 前置条件

- Python 3.13
- Docker
- 有一个正在运行的 Java 应用容器

### 1. 克隆代码

```bash
git clone <你的仓库地址>
cd sre-agent
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
```

Linux 或 macOS:

```bash
source .venv/bin/activate
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

### 3. 安装项目

```bash
pip install --upgrade pip
pip install -e .
```

### 4. 准备配置

复制示例配置：

```bash
cp deploy/examples/tencent-cloud-cvm-2c2g.env .env
```

至少修改这些项：

- `APP_CONTAINER_NAME`
- `APP_CONTAINER_NAMES`，多个容器用逗号分隔
- `WEBHOOK_URL`
- `REPOSITORY_PATH`
- `LOG_CLEAN_PATHS`
- `OPENAI_API_KEY`，用于 DeepSeek OpenAI 兼容接口

### 5. 先跑部署就绪检查`r`n`r`n```bash`r`nPYTHONPATH=src python -m sre_agent.cli.main check-deploy`r`n``` `r`n`r`n这个命令会直接告诉你：`r`n`r`n- 当前是不是 Linux 服务器环境`r`n- Docker 和 Docker daemon 是否可用`r`n- 配置的容器是否能被 Agent 看到`r`n- 当前 autonomous 模式是否启用`r`n- 哪些输入来源可用，哪些会降级或缺失`r`n`r`n### 6. 跑一次单次诊断

```bash
PYTHONPATH=src python -m sre_agent.run
```

如果当前没有异常，输出 `No issues detected.` 是正常现象。

### 7. 跑一次巡检

```bash
PYTHONPATH=src python -m sre_agent.cli.main monitor --once
```

### 8. 持续运行巡检

```bash
PYTHONPATH=src python -m sre_agent.cli.main monitor
```

### 9. 测试通知

```bash
PYTHONPATH=src python -m sre_agent.cli.main test-notify --message "sre agent test"
```

## 服务器部署指南

推荐部署位置：

- 代码目录：`/opt/sre-agent`
- 环境文件：`/etc/sre-agent.env`
- incident 落盘：`/opt/sre-agent/data/incidents.jsonl`

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

这个脚本会自动完成：

- 创建 `.venv`
- 安装项目
- 初始化 `/etc/sre-agent.env`
- 安装 `systemd` 服务
- 执行 `systemctl daemon-reload`

### 3. 修改服务器配置

```bash
vim /etc/sre-agent.env
```

默认模板来自：

- `deploy/examples/tencent-cloud-cvm-2c2g.env`

### 4. 执行服务器自检

```bash
cd /opt/sre-agent
bash deploy/check_server.sh
```

自检会检查：

- Python 是否可用
- Docker 是否可用
- `/etc/sre-agent.env` 是否存在
- 配置里的容器是否可见
- 单次诊断是否能运行

### 5. 启动服务

```bash
systemctl enable sre-agent
systemctl start sre-agent
systemctl status sre-agent
journalctl -u sre-agent -f
```

## 命令行使用方式

### 单次诊断

```bash
python -m sre_agent.cli.main diagnose
```

### 单次巡检

```bash
python -m sre_agent.cli.main monitor --once
```

### 持续巡检

```bash
python -m sre_agent.cli.main monitor
```

### 测试通知

```bash
python -m sre_agent.cli.main test-notify --message "hello from sre-agent"
```

## 配置说明

运行时会按下面顺序加载环境变量文件：

1. 项目根目录 `.env`
2. 用户配置目录 `.env`
3. `/etc/sre-agent.env`

后加载的值会覆盖前面的值。

### 核心配置项

#### 通用配置

- `MODEL`
- `OPENAI_API_KEY`
- `REPOSITORY_PATH`
- `INCIDENT_STORE_PATH`

#### 主机阈值

- `CHECK_INTERVAL_SECONDS`
- `HOST_DISK_PATH`
- `CPU_PERCENT_THRESHOLD`
- `MEMORY_AVAILABLE_THRESHOLD_MB`
- `DISK_THRESHOLD_PERCENT`
- `LOAD_THRESHOLD_PER_CORE`

#### 容器与 JVM

- `APP_CONTAINER_NAME`
- `APP_CONTAINER_NAMES`
- `APP_LOG_SINCE_SECONDS`
- `CONTAINER_RESTART_THRESHOLD`
- `ERROR_BURST_THRESHOLD`
- `FULL_GC_THRESHOLD`
- `JAVA_DIAG_MODE`

#### 业务阈值

- `WORKFLOW_TIMEOUT_SECONDS`
- `WORKFLOW_FAILURE_RATE_THRESHOLD`
- `TOKEN_ANOMALY_THRESHOLD`
- `TOOL_FAILURE_RATE_THRESHOLD`

#### 通知

- `WEBHOOK_URL`
- `WEBHOOK_PROVIDER`
- `WEBHOOK_TIMEOUT_SECONDS`

#### 自动处置

- `AUTO_REMEDIATE`
- `LOG_RETENTION_DAYS`
- `LOG_CLEAN_PATHS`
- `WORKFLOW_CANCEL_URL`
- `WORKFLOW_CANCEL_TOKEN`

## 诊断模式说明

如果配置了 `OPENAI_API_KEY`，系统会通过 OpenAI 兼容接口调用 DeepSeek 生成根因报告。

如果没有配置，或者运行环境里没有相关模型依赖，系统会自动降级为规则化诊断模式，仍然可以正常巡检、落盘和通知。

这意味着你可以先把巡检体系跑起来，再逐步接入大模型。

## 通知方式

当前支持：

- `generic`
- `feishu`

如果 `WEBHOOK_URL` 为空，系统仍然会检测异常和本地落盘，但不会发送通知。

## 自动处置说明

当前白名单动作包括：

- 清理配置目录中的过期日志
- 容器 OOM 后重启容器
- 调用内部接口取消卡住的 workflow

推荐上线顺序：

1. 先开启检测和通知
2. 观察 1 到 2 天误报情况
3. 最后再开启 `AUTO_REMEDIATE=true`

## Java 业务日志要求

要启用业务层监控，Java 应用需要输出结构化 JSON 日志。

详细规范见：

- `docs/业务日志格式规范.md`

当前业务探测器会重点识别：

- `workflow_state`
- `workflow_result`
- `workflow_usage`
- `tool_call`

## 推荐你直接使用的服务器配置模板

仓库已经为你的目标环境生成了一份模板：

- `deploy/examples/tencent-cloud-cvm-2c2g.env`

你可以直接复制：

```bash
cp deploy/examples/tencent-cloud-cvm-2c2g.env /etc/sre-agent.env
vim /etc/sre-agent.env
```

## 验证命令

聚焦测试：

```bash
pytest tests/test_settings.py tests/test_host_detector.py tests/test_java_detector.py tests/test_business_detector.py -v -p no:cacheprovider
```

烟雾验证：

```bash
PYTHONPATH=src python -m sre_agent.run
PYTHONPATH=src python -m sre_agent.cli.main diagnose
PYTHONPATH=src python -m sre_agent.cli.main monitor --once
```

## 当前状态总结

这版仓库已经不是原来的 AWS 日志诊断演示项目，而是一套可以直接放到腾讯云单机服务器上运行的轻量运维 Agent。

如果你下一步继续完善，最优先建议是：

1. 先把 Java 业务结构化日志补齐
2. 根据真实运行情况微调阈值
3. 稳定后再打开自动处置
