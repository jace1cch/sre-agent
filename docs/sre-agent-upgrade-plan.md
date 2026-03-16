# SRE Agent 升级方案

> 基于 fuzzylabs/sre-agent 改造，腾讯云单机 Docker Compose 部署
> 目标：从规则驱动巡检器升级为真正的 ReAct Autonomous Agent

---

## 一、现状与目标

### 当前架构（规则驱动巡检器）

```
monitor CLI → run_cycle() → 规则检测（代码写死）→ fallback 诊断 → JSONL 落盘
```

**核心问题：**
- 编排逻辑全部写死在代码里，LLM 只负责对已收集的 incident 做文字总结
- 无 RAG、无记忆、无动态 Tool 调用
- 没有接 LLM（OPENAI_API_KEY 为空，走 fallback）
- AUTO_REMEDIATE=false，WEBHOOK_URL 为空，通知和处置链路均未启用
- 一轮产生多个 incident 时各自独立处理，不做跨容器合并分析

### 目标架构（ReAct Autonomous Agent）

```
定时触发 → LLM 主动规划任务 → 动态决定 Tool 调用顺序
        → 观察结果 → 继续推理或终止
        → RAG 检索源码 + 历史故障
        → 输出结构化根因报告 + 修改建议
```

**升级后核心能力：**
- LLM 驱动推理闭环，自己决定调哪些工具、按什么顺序
- Prometheus 指标 + Docker 日志 + Java JVM + 业务指标 四层数据融合
- RAG 知识库检索 Java 源码，输出具体代码行修改建议
- 长短期分级记忆，短期滑动窗口 + 长期 pgvector 持久化
- RAGAS 评估基线 + Langfuse 链路追踪

---

## 二、监控数据架构

### 四层监控体系

```
Layer 1：基础设施层（宿主机）
  采集器：node_exporter（9100 端口）
  指标：CPU 使用率 / 内存占用 / 磁盘使用率 / 网络 IO

Layer 2：容器层
  采集器：cAdvisor（8080 端口）
  指标：每个容器的 CPU / 内存 / 网络 / 重启次数

Layer 3：JVM 应用层
  采集器：Micrometer → /actuator/prometheus
  指标：堆内存 / GC 频率 / 线程数 / 连接池状态

Layer 4：业务逻辑层（你的 Coze-like 平台）
  采集器：自定义 Micrometer Counter/Timer/Gauge
  指标：工作流执行成功率 / P95 耗时 / Token 消耗 / MCP Tool 调用失败率
```

### Docker Compose 采集侧部署

在现有 `docker-compose.yml` 追加以下服务：

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
      - prometheus_data:/prometheus

  node-exporter:
    image: prom/node-exporter:latest
    pid: host
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
    ports:
      - "9100:9100"
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'

  cadvisor:
    image: gcr.io/cadvisor/cadvisor:latest
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /sys:/sys:ro
      - /var/lib/docker:/var/lib/docker:ro
    ports:
      - "8080:8080"

  alertmanager:
    image: prom/alertmanager:latest
    ports:
      - "9093:9093"
    volumes:
      - ./alertmanager.yml:/etc/alertmanager/alertmanager.yml

volumes:
  prometheus_data:
```

`prometheus.yml` 抓取配置：

```yaml
scrape_configs:
  - job_name: 'node'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']

  - job_name: 'paiflow-core'
    static_configs:
      - targets: ['paiflow-core-workflow-java:8080']
    metrics_path: '/actuator/prometheus'

  - job_name: 'paiflow-console'
    static_configs:
      - targets: ['paiflow-console-hub:8080']
    metrics_path: '/actuator/prometheus'
```

### Java 业务指标暴露

SpringBoot 添加依赖：

```xml
<dependency>
    <groupId>io.micrometer</groupId>
    <artifactId>micrometer-registry-prometheus</artifactId>
</dependency>
```

自定义业务指标：

```java
@Component
public class WorkflowMetrics {
    private final Counter workflowTotal;
    private final Counter workflowFailed;
    private final Timer   workflowDuration;
    private final Gauge   activeWorkflows;

    public WorkflowMetrics(MeterRegistry registry,
                           WorkflowRepository repo) {
        this.workflowTotal    = Counter.builder("workflow_execution_total")
            .register(registry);
        this.workflowFailed   = Counter.builder("workflow_execution_total")
            .tag("status", "failed").register(registry);
        this.workflowDuration = Timer.builder("workflow_execution_duration")
            .register(registry);
        this.activeWorkflows  = Gauge.builder("workflow_active_count",
            repo, WorkflowRepository::countRunning).register(registry);
    }

    public void recordExecution(boolean success, long durationMs) {
        workflowTotal.increment();
        if (!success) workflowFailed.increment();
        workflowDuration.record(durationMs, TimeUnit.MILLISECONDS);
    }
}
```

---

## 三、ReAct Agent 核心改造

### 3.1 把 agent.py 从"总结器"变成"规划器"

**改造前：**
```python
# LLM 只做一次性总结
def diagnose_incident(incident) -> str:
    prompt = f"这是故障信息: {incident}，请诊断"
    return llm.complete(prompt)
```

**改造后（LangGraph ReAct Loop）：**
```python
from langgraph.prebuilt import create_react_agent
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(model="gpt-4o", temperature=0)

# 把所有工具注册进来
agent = create_react_agent(
    model=llm,
    tools=[
        get_error_logs,
        get_jvm_status,
        query_metric,
        query_metric_range,
        get_active_alerts,
        search_codebase,       # RAG 检索源码
        get_workflow_stats,    # 业务指标
    ],
    checkpointer=MemorySaver()  # 支持断点恢复
)

async def run_inspection(trigger: str):
    result = await agent.ainvoke({
        "messages": [("human", trigger)]
    })
    return result["messages"][-1].content
```

### 3.2 工具层抽象（屏蔽 Docker 与裸进程差异）

```python
class JavaProcessAccessor:
    """统一接口，屏蔽 Docker 容器和裸进程的差异"""
    def get_logs(self, lines=200) -> str: ...
    def run_jstack(self) -> str: ...
    def run_jstat(self) -> str: ...


class DockerJavaAccessor(JavaProcessAccessor):
    def __init__(self, container_name: str):
        self.container = container_name

    def get_logs(self, lines=200) -> str:
        return run_command(f"docker logs --tail {lines} {self.container}")

    def run_jstack(self) -> str:
        return run_command(f"docker exec {self.container} jstack 1")

    def run_jstat(self) -> str:
        return run_command(
            f"docker exec {self.container} jstat -gc 1 1000 3")


class BareProcessJavaAccessor(JavaProcessAccessor):
    def __init__(self, pid: int, log_path: str):
        self.pid = pid
        self.log_path = log_path

    def get_logs(self, lines=200) -> str:
        return run_command(f"tail -n {lines} {self.log_path}")

    def run_jstack(self) -> str:
        return run_command(f"jstack {self.pid}")

    def run_jstat(self) -> str:
        return run_command(f"jstat -gc {self.pid} 1000 3")
```

### 3.3 Prometheus Tool 定义

```python
import requests
from langchain.tools import tool
from datetime import datetime, timedelta

PROMETHEUS_URL = "http://localhost:9090"

@tool
def query_metric(promql: str) -> str:
    """
    执行一条 PromQL 查询，返回当前即时值。
    常用查询示例：
      宿主机CPU:    1 - avg(rate(node_cpu_seconds_total{mode='idle'}[5m]))
      容器内存:     container_memory_usage_bytes{name='paiflow-core-workflow-java'}
      JVM 堆:       jvm_memory_used_bytes{area='heap'}
      GC 频率:      rate(jvm_gc_pause_seconds_count[5m])
      工作流失败率: rate(workflow_execution_total{status='failed'}[5m])
    """
    resp = requests.get(f"{PROMETHEUS_URL}/api/v1/query",
                        params={"query": promql})
    data = resp.json()
    if data["status"] == "success" and data["data"]["result"]:
        results = data["data"]["result"]
        return "\n".join(
            [f"{r['metric']}: {r['value'][1]}" for r in results])
    return f"无数据，PromQL: {promql}"


@tool
def query_metric_range(promql: str, minutes: int = 30) -> str:
    """
    查询某指标过去 N 分钟的趋势，判断是突然飙升还是缓慢增长。
    """
    end   = datetime.now()
    start = end - timedelta(minutes=minutes)
    resp  = requests.get(f"{PROMETHEUS_URL}/api/v1/query_range", params={
        "query": promql,
        "start": start.timestamp(),
        "end":   end.timestamp(),
        "step":  "60s"
    })
    data = resp.json()
    if data["status"] == "success":
        series = data["data"]["result"]
        if not series:
            return "无数据"
        values  = series[0]["values"]
        sampled = values[::max(1, len(values) // 10)]
        lines   = [
            f"{datetime.fromtimestamp(float(t)).strftime('%H:%M')}: {v}"
            for t, v in sampled
        ]
        return "\n".join(lines)
    return "查询失败"


@tool
def get_active_alerts() -> str:
    """
    获取 Alertmanager 当前所有活跃告警，巡检开始时首先调用。
    """
    resp   = requests.get("http://localhost:9093/api/v2/alerts")
    alerts = resp.json()
    if not alerts:
        return "当前无活跃告警"
    lines = []
    for a in alerts:
        name     = a["labels"].get("alertname", "unknown")
        severity = a["labels"].get("severity", "")
        summary  = a["annotations"].get("summary", "")
        lines.append(f"[{severity.upper()}] {name}: {summary}")
    return "\n".join(lines)
```

---

## 四、RAG 知识库

### 4.1 索引内容

```
知识库
├── Java 源码（按类/方法语义切块）
├── incidents.jsonl 历史故障记录
├── 运维手册（排查步骤 / JVM 调优经验）
└── 常见错误码解释
```

### 4.2 源码索引实现

```python
from langchain.document_loaders import DirectoryLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.vectorstores import PGVector
from langchain_openai import OpenAIEmbeddings

# 加载 Java 源码
loader = DirectoryLoader(
    "./your-java-project/src", glob="**/*.java")
docs = loader.load()

# 按 Java 语法边界切块
splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    separators=["\nclass ", "\npublic ", "\nprivate ", "\n\n", "\n"]
)
chunks = splitter.split_documents(docs)

# 存入 pgvector（你已有）
vectorstore = PGVector(
    connection_string=DB_URL,
    embedding=OpenAIEmbeddings()
)
vectorstore.add_documents(chunks)
```

### 4.3 RAG Tool 定义

```python
@tool
def search_codebase(query: str) -> str:
    """
    在项目 Java 源码中语义搜索相关代码片段。
    适用场景：日志中出现异常堆栈时，搜索报错的具体代码行和上下文。
    示例 query: 'WorkflowExecutor line 234 null pointer'
    """
    results = vectorstore.similarity_search(query, k=3)
    return "\n\n---\n\n".join([
        f"文件: {doc.metadata.get('source', 'unknown')}\n{doc.page_content}"
        for doc in results
    ])
```

### 4.4 三角验证推理流程

```
告警触发
  ↓
get_active_alerts()          # 先看已有告警
  ↓
query_metric("工作流失败率") # 确认业务是否受影响
  ↓
query_metric("JVM 堆使用率") # 确认资源水位
  ↓
如果失败率高：
  query_metric_range(失败率趋势, 60)    # 突发还是持续？
  get_error_logs(容器名, 15)            # 具体报什么错
  search_codebase(报错类名 + 行号)      # 定位源码
  ↓
三角验证：指标 + 日志 + 代码 → 根因确认
  ↓
生成修改建议
```

---

## 五、长短期记忆

```python
from langchain.memory import ConversationSummaryBufferMemory
from langchain_community.vectorstores import PGVector

# 短期记忆：滑动窗口，控制 context 长度
short_term_memory = ConversationSummaryBufferMemory(
    llm=llm,
    max_token_limit=2000,   # 超出后自动摘要压缩
    return_messages=True
)

# 长期记忆：事故结束后异步写入 pgvector
async def save_incident_to_memory(incident_summary: str):
    await vectorstore.aadd_texts(
        texts=[incident_summary],
        metadatas=[{
            "type": "incident",
            "timestamp": datetime.now().isoformat(),
            "severity": "HIGH"
        }]
    )

# 检索历史同类故障
@tool
def recall_similar_incidents(description: str) -> str:
    """
    检索历史故障记录，查找相似问题的处置方案。
    """
    results = vectorstore.similarity_search(
        description,
        k=3,
        filter={"type": "incident"}
    )
    return "\n\n".join([doc.page_content for doc in results])
```

---

## 六、定时巡检任务

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler

INSPECTION_PROMPT = """
你是一个 SRE Agent，负责维护以下服务的稳定性：
- paiflow-core-workflow-java（工作流引擎）
- paiflow-console-hub（控制台）

请主动完成一次全面巡检，按以下顺序检查：
1. 先调用 get_active_alerts() 看有无已触发告警
2. 检查宿主机资源水位（CPU / 内存 / 磁盘）
3. 检查 JVM 健康状态（堆内存 / GC 频率）
4. 检查业务指标（工作流成功率 / P95 耗时）
5. 对发现的每个异常深入分析根因，检索相关源码
6. 生成结构化巡检报告

如无异常，输出健康评分和简要摘要即可。
"""

scheduler = AsyncIOScheduler()

@scheduler.scheduled_job('cron', hour='8', minute='0')  # 每天 8 点
async def daily_inspection():
    result = await run_inspection(INSPECTION_PROMPT)
    await send_webhook(result)

@scheduler.scheduled_job('interval', minutes=10)  # 每 10 分钟轻量巡检
async def quick_check():
    prompt = "快速检查：有无活跃告警？工作流失败率是否正常？只需 2-3 步工具调用。"
    result = await run_inspection(prompt)
    if "异常" in result or "告警" in result:
        await send_webhook(result)

scheduler.start()
```

---

## 七、结构化输出格式

```json
{
  "inspection_time": "2025-03-15T10:30:00",
  "severity": "HIGH",
  "root_cause": "WorkflowExecutor.java:234 存在 NPE 风险，MCP Tool 返回空结果时未做防御",
  "evidence": {
    "alert": "[HIGH] WorkflowFailureRateHigh: 失败率 23%，超过阈值 10%",
    "metric": "workflow_execution_total{status='failed'}: 0.23/s",
    "error_log": "NullPointerException at WorkflowExecutor.java:234",
    "related_code": "String result = toolResponse.getData().toString();"
  },
  "suggestion": {
    "file": "WorkflowExecutor.java",
    "line": 234,
    "before": "String result = toolResponse.getData().toString();",
    "after": "String result = (toolResponse != null && toolResponse.getData() != null) ? toolResponse.getData().toString() : \"\";",
    "reason": "防止 MCP Tool 超时或返回空响应时触发 NPE"
  },
  "react_steps": 4,
  "tools_called": ["get_active_alerts", "query_metric", "get_error_logs", "search_codebase"],
  "health_score": 72
}
```

---

## 八、评估体系（RAGAS + Langfuse）

```python
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall
)

# 构造 golden dataset（20-30 个故障场景）
golden_dataset = [
    {
        "question": "容器 paiflow-core 在 03:42 发生了什么？",
        "ground_truth": "NullPointerException at WorkflowExecutor.java:234，"
                        "原因是 MCP Tool 返回空结果未做 null 检查",
        "contexts": [error_log, relevant_code_snippet]
    },
    # ... 更多 case
]

result = evaluate(
    dataset=golden_dataset,
    metrics=[faithfulness, answer_relevancy, context_precision, context_recall]
)
print(result)
# {'faithfulness': 0.87, 'answer_relevancy': 0.91, ...}
```

Langfuse 链路追踪：

```python
from langfuse.callback import CallbackHandler

langfuse_handler = CallbackHandler(
    public_key="your-public-key",
    secret_key="your-secret-key"
)

# 每次 Agent 推理时传入
result = await agent.ainvoke(
    {"messages": [("human", prompt)]},
    config={"callbacks": [langfuse_handler]}
)
```

---

## 九、改造优先级路线图

| 阶段 | 任务 | 预计时间 | 简历亮点 |
|---|---|---|---|
| **P0** | 接入 LLM，把 agent.py 改成 LangGraph ReAct Loop | 3-5 天 | ReAct 推理闭环 |
| **P0** | 把 host.py / docker.py / java.py 重构为 LangChain Tool | 3 天 | 动态 Tool 调用链路 |
| **P1** | 部署 Prometheus + node_exporter + cAdvisor，封装三个 PromQL Tool | 3 天 | 四层监控 + 时序数据分析 |
| **P1** | SpringBoot 接入 Micrometer，暴露业务指标 | 2 天 | 业务维度可观测性 |
| **P2** | 建 RAG 知识库，索引 Java 源码 + incidents.jsonl | 3 天 | RAG 源码检索 + 修改建议 |
| **P2** | 长短期分级记忆 + 历史故障召回 | 2 天 | 记忆机制 + 经验积累 |
| **P3** | 定时巡检任务 + 结构化报告输出 | 2 天 | 自动化日报 |
| **P3** | RAGAS 评估基线 + Langfuse 链路追踪 | 2 天 | 可观测性 + 评估指标 |

---

## 十、典型故障场景 Agent 处理示例

### 场景一：工作流 Token 超支

```
监控：某 workflow 推理耗时 > 30s，Token 消耗 > 20k
Agent 推理链路：
  1. query_metric("工作流 P95 耗时")         → 确认异常范围
  2. get_error_logs("paiflow-core", 30)      → 找对应 workflow ID
  3. search_codebase("workflow token limit")  → 检查是否有超时控制
  4. recall_similar_incidents("token 超支")  → 召回历史同类处置
输出：该 workflow system prompt 缺少终止条件，建议第 89 行加 max_steps 限制
```

### 场景二：2G 内存撑不住

```
监控：JVM 堆 > 90%，Full GC > 1次/分钟
Agent 推理链路：
  1. query_metric_range("堆内存趋势", 60)    → 判断是持续增长还是突发
  2. query_metric("各工作流并发数")          → 发现某用户并发 20 个
  3. get_jvm_status("jstack")               → 确认线程阻塞情况
  4. search_codebase("线程池配置")           → 检查并发限制代码
输出：并发超限导致堆压力，建议在第 45 行加用户级并发限流
```

### 场景三：磁盘告警

```
监控：磁盘使用率 > 85%
Agent 推理链路：
  1. query_metric("各目录磁盘占用")          → 定位是哪个目录
  2. get_disk_detail("/opt/app/logs")        → 确认是日志文件
输出：自动清理 7 天前日志，释放约 800MB，建议加 logrotate 配置
```

---

## 十一、简历描述模板

```
基于 fuzzylabs/sre-agent 进行系统性改造，将规则驱动的巡检器升级为
真正的 ReAct Autonomous Agent：

• 架构改造：使用 LangGraph 实现 ReAct 推理闭环，LLM 主动规划任务、
  动态决定 Tool 调用顺序，替代原有写死的编排逻辑

• 监控体系：集成 Prometheus + node_exporter + cAdvisor + Micrometer，
  实现基础设施 / 容器 / JVM / 业务四层指标采集，封装 PromQL Tool
  供 LLM 动态查询时序数据

• RAG 增强：构建 pgvector 知识库，索引 Java 源码和历史故障记录，
  Agent 定位报错后自动检索相关代码，生成具体修改建议（精确到文件行号）

• 三角验证：指标异常 + 日志报错 + 源码定位三路并行，显著降低误报率

• 评估体系：使用 RAGAS 建立评估基线（Faithfulness 0.87），
  Langfuse 追踪每次推理链路的 Token 消耗和 Tool 调用序列

部署环境：腾讯云 CVM（2核2G）+ Docker Compose，资源受限环境下
完成完整 Agent 推理闭环验证
```

---

*文档生成时间：2025-03-15*
