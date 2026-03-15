# 腾讯云单机 Java 运维 Agent MVP 改造方案

## 1. 文档目标

本文档用于把当前开源项目 `sre-agent` 改造成适合你个人平台的最小可行版本，目标是在腾讯云 2 核 2G CVM 上监控 Docker 部署的 Java 应用，并实现以下三类能力：

- 告警通知
- 智能处置
- 根因报告

重点不是做一个很重的通用平台，而是尽快做出一个能在你自己服务器上稳定跑起来、能发现问题、能自动做少量安全动作、能输出有价值报告的 MVP。

## 2. 先理解原开源项目

当前仓库本质上是一个“被动触发的诊断 Agent”，不是一个完整的监控平台。

### 2.1 原项目核心链路

原项目主链路是：

1. 外部监控系统先发现异常。
2. Agent 从 CloudWatch 拉错误日志。
3. Agent 通过 GitHub MCP 查代码。
4. Agent 生成诊断结果。
5. Agent 通过 Slack MCP 发通知。

对应到代码层，真正最有价值、最值得保留的部分是：

- `src/sre_agent/core/agent.py`: Agent 组装与诊断入口
- `src/sre_agent/core/models.py`: 结构化输出模型
- `src/sre_agent/core/prompts.py`: Prompt 装载逻辑
- `src/sre_agent/run.py`: 单次诊断入口
- `src/sre_agent/core/settings.py`: 配置模型思路

### 2.2 原项目和你目标的错位点

你的目标是“腾讯云单机 + Docker Java 应用 + 智能运维”，而原项目偏向“AWS 生态里的日志诊断助手”。

主要错位如下：

- 依赖 CloudWatch，不适合直接监控腾讯云 CVM 本机与 Docker
- 依赖 GitHub MCP 和 Slack MCP，部署复杂度高
- 缺少主动巡检能力，原项目更像被告警触发后的分析器
- 没有主机层、JVM 层、业务层三层监控闭环
- 没有安全收敛过的自动处置框架
- 带有较重的 AWS ECS 远端部署向导，这对你的单机场景是冗余设计

结论：

这个项目适合“借骨架，不照抄架构”。

## 3. 方案选型

### 方案 A: 尽量保留原设计，只把 AWS 换成腾讯云

做法：继续走云日志平台 + MCP 集成 + Agent 诊断。

优点：

- 复用原项目较多

缺点：

- 仍然偏重
- 仍然不是单机优先设计
- 监控、处置、数据采集都要补很多东西

不推荐作为 MVP。

### 方案 B: 保留 Agent 核心，改成单机本地巡检架构

做法：保留 `pydantic-ai + 结构化诊断输出`，把 CloudWatch/GitHub MCP/Slack MCP 全部替换成“本机采集 + Docker 日志 + JVM 诊断 + Webhook 通知”。

优点：

- 改造成本最低
- 与你的腾讯云单机环境最匹配
- 最容易做出可运行 MVP
- 后续也能逐步扩成更完整平台

缺点：

- 第一个版本不追求大而全
- 代码托管分析能力会从 GitHub MCP 降级为本地源码检索

这是推荐方案。

### 方案 C: 直接上 Prometheus + Grafana + Alertmanager + AI Agent

优点：

- 长期可扩展性最好
- 监控体系标准化

缺点：

- 对 2 核 2G 机器偏重
- 部署与维护复杂度明显上升
- 不能最快落地 MVP

建议放到第二阶段，而不是第一阶段。

## 4. MVP 设计原则

### 4.1 一句话原则

先做“轻量巡检器 + 受控诊断 Agent + 白名单自动处置 + Webhook 通知”，不要一开始做成通用 AIOps 平台。

### 4.2 必须坚持的原则

- Agent 不跑本地大模型，只调用远端模型 API
- 自动处置只允许白名单动作，禁止 LLM 自由执行任意 shell
- 监控数据优先来自本机、Docker、应用日志，不先引入重型观测平台
- 业务层监控优先依赖结构化业务日志，不先做复杂数据库对接
- 每次事故都保留证据快照，方便复盘和调 Prompt

### 4.3 MVP 暂时不做

- AWS ECS 远端部署向导
- Slack MCP / GitHub MCP / CloudWatch 三件套
- 完整评测框架接入生产链路
- 多主机、多集群、多租户
- 自主式高风险修复动作
- 本地推理模型

## 5. 目标架构

推荐把系统改造成 6 个轻量模块：

1. `monitor`: 定时巡检
2. `detectors`: 各层异常检测
3. `evidence`: 证据采集
4. `diagnoser`: LLM 根因分析
5. `executor`: 白名单处置器
6. `notifier`: Webhook 通知

建议运行形态：

- 以 `systemd` 服务直接部署在 CVM 宿主机上
- 每 60 秒巡检一次
- 异常时立即采集证据、生成报告、执行低风险动作、发送通知

这比把 Agent 自己也放进 Docker 更适合 MVP，因为：

- 更容易读主机指标
- 更容易访问 Docker CLI
- 更容易调用 `docker exec`
- 更容易落地 `systemd` 和本地持久化

## 6. 三层监控如何落地

下面按你 `docs/项目修改方向.md` 的目标做落地拆解。

### 6.1 第一层: 基础设施层

#### 监控项

- CPU 使用率
- Load Average
- 可用内存
- 磁盘使用率
- Docker 容器状态
- 容器重启次数
- 容器是否 OOMKilled

#### 数据来源

- `psutil`
- `docker ps`
- `docker inspect`
- `df -h`

#### MVP 阈值建议

- CPU > 85% 且持续 3 分钟
- 可用内存 < 200 MB
- 磁盘使用率 > 85%
- 应用容器 10 分钟内重启次数 > 1
- `OOMKilled=true`

#### 自动处置

- 磁盘 > 85%: 清理指定目录 30 天前日志
- 容器 OOMKilled: 先采集日志与容器状态，再重启容器
- 容器反覆重启: 暂不自动重启多次，只告警并附证据

### 6.2 第二层: Java 应用层

#### 监控项

- `ERROR` 日志每分钟数量
- JVM GC 异常
- Full GC 出现次数
- 堆内存占用趋势
- 线程阻塞情况
- 接口响应时间异常

#### 数据来源

- `docker logs --since`
- GC 日志
- `docker exec` 进入容器执行诊断命令
- 应用 access log 或 Spring Boot Actuator

#### MVP 最小实现建议

先做下面四项：

- `ERROR` 日志突增
- Full GC / 高频 GC
- OOM 关键字检测
- 异常时抓线程栈

接口 RT 监控放入 P1，优先从以下两种来源二选一：

- 已有 access log 统计
- 已开启 `actuator/prometheus`

#### 线程栈采集建议

优先级如下：

1. 如果容器内有 JDK 工具，使用 `jstack` 或 `jcmd Thread.print`
2. 如果没有，发送 `SIGQUIT` 给 JVM，把线程栈打到容器日志

这样可以避免为了 MVP 强行改 Java 镜像。

### 6.3 第三层: 业务逻辑层

这一层是你最有价值的差异化能力。

#### 监控项

- 工作流执行成功率
- 工作流失败节点
- Token 消耗异常
- MCP Tool 调用失败率
- 工作流 running 超时卡住

#### MVP 推荐实现方式

不要先接数据库，先要求 Java 应用输出结构化业务日志到 stdout。

建议日志字段至少包括：

- `event_type`
- `workflow_id`
- `node_id`
- `status`
- `elapsed_ms`
- `tool_name`
- `error_code`
- `token_input`
- `token_output`
- `trace_id`

有了这些字段，Agent 就能直接从 Docker 日志里做：

- 失败率统计
- 卡住检测
- Token 异常检测
- 工具失败聚合

#### MVP 阈值建议

- 单次 workflow token > 50k
- workflow `running` 超过 5 分钟无状态变化
- tool 调用失败率 5 分钟内 > 30%
- workflow 失败率 5 分钟内 > 20%

#### 自动处置

- 工作流卡住: 优先调用你平台的内部管理接口做 terminate/cancel
- 如果还没有管理接口，MVP 只告警，不自动 kill 业务进程

## 7. 推荐的 MVP 工作流

### 7.1 巡检流程

1. 每 60 秒跑一次巡检。
2. 各 detector 输出结构化事件。
3. 事件进入本地去重与抑制逻辑。
4. 命中异常后先采集证据快照。
5. 再调用 LLM 生成根因报告。
6. 如果命中白名单处置条件，则执行自动处置。
7. 发送通知并落库。

### 7.2 根因分析流程

输入给 LLM 的不是原始全量日志，而是精简后的“事故证据包”：

- 主机指标快照
- 容器状态
- 最近日志摘要
- 关键异常日志片段
- JVM 线程栈摘要
- GC 摘要
- 可选的源码检索结果

这样做的好处：

- Token 成本低
- 报告更稳定
- 更容易做结构化输出

### 7.3 自动处置流程

MVP 只允许 3 类动作：

- `clean_old_logs`
- `restart_container`
- `cancel_stuck_workflow`

执行策略：

- 先采证，后处置
- 每次动作都记录执行原因、执行结果、耗时
- 高风险动作默认不开启

## 8. 对原项目的删减建议

### 8.1 建议保留

- `src/sre_agent/core/agent.py`
- `src/sre_agent/core/models.py`
- `src/sre_agent/core/prompts.py`
- `src/sre_agent/run.py`
- `src/sre_agent/cli/main.py` 的 Click 入口思路

### 8.2 建议替换

- `src/sre_agent/core/tools/cloudwatch.py`
  - 替换为本地日志与主机探针工具
- `src/sre_agent/core/tools/github.py`
  - 替换为本地源码检索工具
- `src/sre_agent/core/tools/slack.py`
  - 替换为通用 Webhook 通知器
- `src/sre_agent/core/settings.py`
  - 改成面向单机 + Docker + Java 的简化配置

### 8.3 建议移除或下沉到后续阶段

- `src/sre_agent/core/deployments/aws_ecs/*`
- `src/sre_agent/cli/mode/remote/*`
- `src/sre_agent/cli/configuration/providers/aws.py`
- `src/sre_agent/cli/configuration/wizard.py`
- `docker-compose.yaml` 中仅服务于 Slack MCP 的内容
- `src/sre_agent/eval/*` 先不进入 MVP 主链路

这部分代码不是完全没价值，但对你的 MVP 会明显增加认知负担和维护成本。

## 9. 建议的新目录结构

```text
src/sre_agent/
  cli/
    main.py
  core/
    agent.py
    models.py
    prompts.py
    settings.py
  monitor/
    scheduler.py
    service.py
  detectors/
    host.py
    docker.py
    java.py
    business.py
  evidence/
    collector.py
    summariser.py
  actions/
    executor.py
    playbooks.py
  notify/
    webhook.py
  storage/
    incidents.py
  utils/
    shell.py
    time.py
  run.py
```

## 10. 建议的新命令模型

交互式花哨 CLI 没必要保留，MVP 只保留 3 个命令：

- `sre-agent monitor`
  - 常驻或轮询巡检
- `sre-agent diagnose`
  - 对指定容器或时间窗口做一次手动诊断
- `sre-agent test-notify`
  - 测试通知链路

如果还需要一个调试命令，可以加：

- `sre-agent collect-evidence`

## 11. 配置设计建议

MVP 的配置应该从原来 AWS/GitHub/Slack 三套配置，改成单机可读的一套：

- `MODEL`
- `MODEL_API_KEY`
- `WEBHOOK_URL`
- `CHECK_INTERVAL_SECONDS`
- `APP_CONTAINER_NAME`
- `APP_LOG_SINCE_SECONDS`
- `REPO_PATH`
- `AUTO_REMEDIATE`
- `LOG_RETENTION_DAYS`
- `LOG_CLEAN_PATHS`
- `WORKFLOW_TIMEOUT_SECONDS`
- `TOKEN_ANOMALY_THRESHOLD`
- `JAVA_DIAG_MODE`

其中：

- `REPO_PATH` 用于本地代码检索
- `JAVA_DIAG_MODE` 可选 `jstack` / `jcmd` / `sigquit`
- `AUTO_REMEDIATE` 默认建议为 `false`

## 12. MVP 中 Agent 应该怎么用

不建议让 Agent 负责“发现异常”。

MVP 中更合理的职责分工是：

- 规则引擎负责发现异常
- 证据采集器负责采集上下文
- Agent 负责归因、解释、建议和生成报告
- 执行器负责按白名单动作落地处置

这是最关键的设计收敛。

这样做比“让 LLM 全程自主巡检和执行”更稳，也更适合 2 核 2G 环境。

## 13. 根因报告建议格式

每次事故通知建议输出以下字段：

- 事故等级
- 事故摘要
- 影响范围
- 直接症状
- 根因判断
- 关键证据
- 已执行动作
- 建议人工处理项
- 风险评估
- 时间线

如果能定位到源码，再补一段：

- 疑似类 / 方法 / 文件路径

MVP 的代码定位建议基于“异常堆栈 + 本地 `rg` 检索”，不要先恢复 GitHub MCP。

## 14. 自动处置安全边界

MVP 的自动处置一定要加防线：

- 同一事故 10 分钟内不重复执行同一动作
- 重启容器最多连续执行 1 次
- 磁盘清理只允许清理白名单目录
- 业务终止动作必须只调用你明确提供的内部管理接口
- 所有动作先记录，再执行

这部分建议通过本地 SQLite 做幂等与审计。

## 15. 部署建议

### 15.1 推荐部署方式

在腾讯云 CVM 上直接部署为宿主机服务：

- 代码目录: `/opt/sre-agent`
- 数据目录: `/var/lib/sre-agent`
- 日志目录: `/var/log/sre-agent`
- 配置文件: `/etc/sre-agent.env`
- 运行方式: `systemd`

### 15.2 推荐依赖

- Python 3.13
- Docker CLI
- 访问 Docker 的权限
- Webhook 机器人
- 远端大模型 API Key

### 15.3 Java 侧最小配合项

为了让这个运维 Agent 真正“懂业务”，Java 应用至少配合两件事：

1. 输出结构化业务日志
2. 开启 GC 日志

如果条件允许，再增加：

3. 暴露 Actuator 指标
4. 提供 workflow 管理接口

## 16. 推荐的 MVP 版本边界

### P0 必做

- 主机 CPU / 内存 / 磁盘检测
- Docker 容器状态 / OOM / 重启检测
- `ERROR` 日志突增检测
- OOM 与 Full GC 检测
- 结构化业务日志解析
- Webhook 告警
- 3 个白名单动作
- 根因报告输出

### P1 增强

- 接口 RT 异常检测
- 本地源码定位到类和方法
- workflow 卡住自动终止
- 去重、静默、合并告警更完善

### P2 后续演进

- 接 Prometheus / Grafana
- 多容器、多应用
- 更丰富的评测集
- 更强的变更关联分析

## 17. 我对这个项目的最终建议

如果你的目标是“最快做出自己的运维 Agent”，那就不要沿着原项目的 AWS 远端部署路径继续堆功能。

最优路线是：

- 保留原项目的 Agent 核心和结构化输出思路
- 删除 CloudWatch / GitHub MCP / Slack MCP 依赖
- 删除 AWS ECS 部署链路
- 新增本机巡检、Docker 检测、JVM 诊断、业务日志解析、Webhook 通知、白名单处置
- 把 Agent 收敛为“诊断与报告中枢”，不是“无限制自治执行器”

一句话总结：

> 这个项目的 MVP 应该从“云上日志诊断助手”改造成“单机轻量运维值班员”。

## 18. 下一步实现顺序建议

建议严格按下面顺序做，最快出结果：

1. 先砍掉 AWS ECS / MCP 相关入口
2. 把配置改成单机版
3. 做主机 + Docker + 日志巡检
4. 做 Webhook 告警
5. 做证据采集与根因报告
6. 最后再加自动处置

这个顺序能保证你很快看到第一个闭环版本跑起来。
