# ReAct + LangGraph Autonomous SRE Agent Implementation Plan

> **For Codex:** REQUIRED SUB-SKILL: Use `executing-plans` to implement this plan task-by-task.

**Goal:** Upgrade the current rule-driven single-host SRE monitor into a ReAct + LangGraph autonomous SRE agent with dynamic tool orchestration, Prometheus-backed metrics analysis, RAG over source code and incident history, tiered memory, structured remediation reports, and evaluation tracing.

**Architecture:** Keep the current detector stack as the low-level evidence collection layer, but replace the fixed per-container orchestration with a cycle-level LangGraph workflow. The graph should plan, select tools, observe outputs, retrieve source and historical context, correlate multiple findings into one or more incidents, and then emit a structured report. This plan interprets the user request as **ReAct + LangGraph**, not a React front end, because `sre-agent-upgrade-plan.md` consistently describes a ReAct autonomous agent.

**Tech Stack:** Python 3.13, subject to an early compatibility check for LangGraph and RAGAS before dependency versions are locked, plus LangChain, LangChain OpenAI, Pydantic, httpx, Prometheus, Micrometer, PostgreSQL + pgvector, Langfuse, and pytest.

---

## Recommended approach

**Recommended option:** Layer LangGraph on top of the current monitor codebase instead of rewriting the project from scratch.

Why this option is the best fit:
- The current repository already has stable detectors, incident models, storage, notification, and remediation boundaries.
- The upgrade document鈥檚 main gap is orchestration and retrieval, not raw evidence collection.
- This approach keeps risk low, shortens delivery time, and preserves a useful fallback mode when LLM, Prometheus, or pgvector are unavailable.

Alternatives considered:
- **Full rewrite:** clean boundaries, but too much delivery risk and too little reuse.
- **Keep the current monitor loop and add more heuristics:** fast, but it does not meet the document goal of LLM-led tool planning and autonomous reasoning.

---

## Delivery principles

- Preserve the existing CLI and monitoring behaviour until the LangGraph path is verified.
- Keep the current monitor loop available behind a legacy path until the autonomous path is proven safe.
- Fix the architectural root cause: the project currently analyses host and container findings independently. The new graph must support cross-container and cross-signal correlation within one monitoring cycle.
- Keep every external integration behind a thin adapter so local tests can stub them easily.
- Prefer deterministic fallbacks when an external dependency is unavailable.
- Keep heavy evaluation and tracing work off the 2 core, 2 GB production host wherever possible.
- Keep documentation and deployment assets in the repo so the upgrade is reproducible.

---

### Task 1: Expand runtime configuration for the autonomous stack

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `src/sre_agent/core/settings.py`
- Modify: `deploy/examples/tencent-cloud-cvm-2c2g.env`
- Modify: `tests/test_settings.py`

**Step 1: Write the failing settings tests**

- Add tests for new configuration groups:
  - LangGraph and model runtime
  - Prometheus endpoint access
  - pgvector storage
  - embeddings and retrieval
  - Langfuse tracing
  - RAGAS evaluation
- Add tests that ensure current environment variables remain backwards compatible.

**Step 2: Add the new dependencies**

- Add at least:
  - `langgraph`
  - `langchain`
  - `langchain-openai`
  - `langchain-community`
  - `httpx`
  - `pgvector`
  - `psycopg[binary]`
  - `langfuse`
  - `ragas`
- Before locking versions, add a minimal Python 3.13 compatibility smoke test for the LangGraph and RAGAS import path.
- Keep existing dependencies until the old code path is removed.

**Step 3: Extend `AgentSettings`**

- Add new settings with safe defaults:
  - `GRAPH_MAX_STEPS`
  - `GRAPH_ENABLE_AUTONOMOUS_LOOP`
  - `PROMETHEUS_BASE_URL`
  - `PROMETHEUS_TIMEOUT_SECONDS`
  - `PROMETHEUS_STEP_SECONDS`
  - `VECTOR_DB_DSN`
  - `VECTOR_DB_TABLE_PREFIX`
  - `EMBEDDING_MODEL`
  - `EMBEDDING_DIMENSIONS`
  - `RAG_TOP_K`
  - `LANGFUSE_PUBLIC_KEY`
  - `LANGFUSE_SECRET_KEY`
  - `LANGFUSE_HOST`
  - `RAGAS_DATASET_PATH`
  - `CODEBASE_PATH`
  - `CODEBASE_FETCH_MODE`
  - `CODEBASE_GIT_URL`
  - `CODEBASE_GIT_BRANCH`
  - `CODEBASE_CACHE_PATH`
  - `CODEBASE_INCLUDE_GLOBS`
  - `CODEBASE_EXCLUDE_GLOBS`
- Keep `OPENAI_API_KEY`, `OPENAI_BASE_URL`, container settings, and remediation settings compatible.

**Step 4: Update the example environment file**

- Add commented sections for each new capability.
- Mark optional values clearly so a single-host local run still works without Prometheus, pgvector, Langfuse, or RAGAS.

**Step 5: Run the focused tests**

Run: `pytest tests/test_settings.py -v`

Expected:
- New settings parse correctly.
- Existing settings remain valid.

**Step 6: Commit**

Run: `git add pyproject.toml uv.lock src/sre_agent/core/settings.py deploy/examples/tencent-cloud-cvm-2c2g.env tests/test_settings.py`

Run: `git commit -m "feat: add autonomous agent settings"`

---

### Task 2: Introduce cycle-level state and pragmatic correlation models

**Files:**
- Modify: `src/sre_agent/core/models.py`
- Create: `src/sre_agent/core/cycle.py`
- Create: `tests/test_cycle_models.py`

**Step 1: Write the failing model tests**

- Add tests for new cycle-level structures:
  - `CycleObservation`
  - `CycleTarget`
  - `ToolCallRecord`
  - `GraphReasoningStep`
  - `IncidentCluster`
  - `AutonomousReport`
- Add a test that groups incidents into the same five-minute window before any LLM reasoning.

**Step 2: Add new domain models**

- Keep the current `Incident`, `MonitorFinding`, and `EvidenceBundle` models.
- Add cycle-level models that allow the graph to reason over all findings from one run, not only one container.
- Make `IncidentCluster` pragmatic for the first version:
  - include `window_start`
  - include `window_end`
  - include `incidents`
  - include `correlation_method`
- Define `correlation_method` as one of:
  - `time_window`
  - `shared_error`
  - `llm_inferred`
- Add structured output fields required by the upgrade document:
  - `root_cause`
  - `confidence_score`
  - `health_score`
  - `react_steps`
  - `tools_called`
  - `code_suggestions`
  - `memory_hits`

**Step 3: Add a small correlation helper**

- Put correlation helpers in `src/sre_agent/core/cycle.py`.
- Start with deterministic grouping by time window, container name, and shared error signatures.
- Treat workflow IDs and trace IDs as optional enrichment when they become available later.
- Keep the helper pure so it can be reused in tests and in the graph node.

**Step 4: Run the focused tests**

Run: `pytest tests/test_cycle_models.py -v`

Expected:
- Cycle-level models serialise correctly.
- Deterministic grouping works for time-window and shared-error cases.

**Step 5: Commit**

Run: `git add src/sre_agent/core/models.py src/sre_agent/core/cycle.py tests/test_cycle_models.py`

Run: `git commit -m "feat: add pragmatic cycle correlation models"`

---

### Task 3: Introduce LangChain tools in two phases

**Files:**
- Create: `src/sre_agent/tools/__init__.py`
- Create: `src/sre_agent/tools/registry.py`
- Create: `src/sre_agent/tools/host.py`
- Create: `src/sre_agent/tools/docker.py`
- Create: `src/sre_agent/tools/java.py`
- Create: `src/sre_agent/tools/business.py`
- Create: `src/sre_agent/tools/prometheus.py`
- Create: `src/sre_agent/tools/repository.py`
- Create: `src/sre_agent/tools/incidents.py`
- Modify later in phase 2: `src/sre_agent/detectors/host.py`
- Modify later in phase 2: `src/sre_agent/detectors/docker.py`
- Modify later in phase 2: `src/sre_agent/detectors/java.py`
- Modify later in phase 2: `src/sre_agent/detectors/business.py`
- Create: `tests/test_tool_registry.py`
- Create: `tests/test_prometheus_tools.py`
- Create: `tests/test_repository_tools.py`

**Step 1: Write the failing tool tests**

- Add tests that verify:
  - every tool has a stable name and JSON-serialisable result
  - stub tools can be registered and invoked without touching the current detector path
  - Prometheus tools format queries correctly
  - repository search respects include and exclude globs
  - incident recall reads stored snapshots without loading the whole file into memory

**Step 2: Phase 1, create tool contracts without changing detectors**

- Create the `tools/` package and the registry first.
- Use mock-friendly adapters backed by the current shell and storage utilities.
- Do not modify detector threshold logic in this phase.
- Ensure Task 5 can run entirely against stub or fake tool implementations.

**Step 3: Build the initial tool registry**

- Register at least these tools from the upgrade document:
  - `get_active_alerts`
  - `query_metric`
  - `query_metric_range`
  - `get_error_logs`
  - `get_jvm_status`
  - `get_disk_detail`
  - `search_codebase`
  - `recall_similar_incidents`
- Return consistent dictionaries with `status`, `summary`, `data`, and `source` keys.

**Step 4: Add safe fallbacks**

- If Prometheus is not configured, the Prometheus tools should return a structured unavailable response.
- If the repository path is not configured, `search_codebase` should return a structured unavailable response.
- If incident history is empty, `recall_similar_incidents` should return an empty result without error.

**Step 5: Run phase 1 tests**

Run: `pytest tests/test_tool_registry.py tests/test_prometheus_tools.py tests/test_repository_tools.py -v`

Expected:
- All tools are registered.
- Missing integrations degrade gracefully.
- The graph can consume stub tools without depending on detector refactors.

**Step 6: Phase 2, migrate shared evidence helpers after Task 4 and Task 5 are stable**

- Keep detectors focused on threshold logic.
- Move reusable evidence access into tool modules only after the graph skeleton and Prometheus client are working.
- Preserve detector interfaces so the legacy path continues to run unchanged.

**Step 7: Commit**

Run: `git add src/sre_agent/tools src/sre_agent/detectors tests/test_tool_registry.py tests/test_prometheus_tools.py tests/test_repository_tools.py`

Run: `git commit -m "feat: introduce tool registry in phases"`

---

### Task 4: Add the Prometheus client and observability deployment bundle

**Files:**
- Create: `src/sre_agent/observability/__init__.py`
- Create: `src/sre_agent/observability/prometheus_client.py`
- Create: `deploy/observability/docker-compose.yml`
- Create: `deploy/observability/prometheus.yml`
- Create: `deploy/observability/alertmanager.yml`
- Modify: `README.md`
- Modify: `docs/鏈嶅姟鍣ㄩ儴缃茶鏄?md`
- Create: `tests/test_prometheus_client.py`

**Step 1: Write the failing Prometheus client tests**

- Add tests for instant query, range query, timeout handling, and parse errors.

**Step 2: Implement the Prometheus HTTP adapter**

- Use `httpx` with small timeouts.
- Keep request and response mapping isolated in one module.
- Return small, graph-friendly summaries rather than raw payloads.

**Step 3: Add a reproducible observability bundle**

- Add a minimal Docker Compose stack that includes:
  - Prometheus
  - node_exporter
  - cAdvisor
  - Alertmanager
- Add scrape config examples for Java app metrics at `/actuator/prometheus`.

**Step 4: Update deployment documentation**

- Document how to start the observability stack.
- Document which endpoints the Python agent expects.
- Keep instructions suitable for a 2 core, 2 GB single-host environment.

**Step 5: Run the focused tests**

Run: `pytest tests/test_prometheus_client.py tests/test_prometheus_tools.py -v`

Expected:
- Prometheus client behaviour is covered.
- Tool behaviour stays stable.

**Step 6: Commit**

Run: `git add src/sre_agent/observability deploy/observability README.md docs/鏈嶅姟鍣ㄩ儴缃茶鏄?md tests/test_prometheus_client.py`

Run: `git commit -m "feat: add Prometheus integration assets"`

---

### Task 5: Build the LangGraph workflow and ReAct execution loop

**Files:**
- Create: `src/sre_agent/graph/__init__.py`
- Create: `src/sre_agent/graph/state.py`
- Create: `src/sre_agent/graph/nodes.py`
- Create: `src/sre_agent/graph/workflow.py`
- Create: `src/sre_agent/graph/policies.py`
- Modify: `src/sre_agent/core/agent.py`
- Modify: `src/sre_agent/core/prompts.py`
- Modify: `src/sre_agent/core/prompts/system_prompt.txt`
- Modify: `src/sre_agent/core/prompts/diagnosis_prompt.txt`
- Create: `tests/test_graph_workflow.py`
- Create: `tests/test_graph_policies.py`

**Step 1: Write the failing workflow tests**

- Add tests for:
  - plan node initialises a tool budget
  - tool execution appends observations to state
  - loop termination after `GRAPH_MAX_STEPS`
  - fallback report generation when the model call fails
  - graph output includes tool names and reasoning steps
  - the graph can run end-to-end with stub tools before any detector migration

**Step 2: Introduce a graph state object**

- Store:
  - cycle observation
  - correlated incident clusters
  - planned next actions
  - tool call records
  - retrieved context
  - memory hits
  - report draft

**Step 3: Implement the graph nodes**

- Add separate nodes for:
  - initial planning
  - tool selection
  - tool execution
  - retrieval enrichment
  - report synthesis
  - termination and fallback
- Keep each node small and pure where possible.

**Step 4: Replace the old one-shot diagnosis path**

- Keep `diagnose_incident()` as a compatibility fa莽ade.
- Route to the LangGraph workflow when `GRAPH_ENABLE_AUTONOMOUS_LOOP=true`.
- Keep the deterministic fallback for non-LLM runs.

**Step 5: Add execution policy guards**

- Enforce a tool budget and step budget.
- Disallow unrestricted shell execution from the graph.
- Limit remediation suggestions to the current whitelist.

**Step 6: Run the focused tests**

Run: `pytest tests/test_graph_workflow.py tests/test_graph_policies.py -v`

Expected:
- The graph compiles.
- The graph exits cleanly on success and on fallback.

**Step 7: Commit**

Run: `git add src/sre_agent/graph src/sre_agent/core/agent.py src/sre_agent/core/prompts.py src/sre_agent/core/prompts tests/test_graph_workflow.py tests/test_graph_policies.py`

Run: `git commit -m "feat: add LangGraph autonomous workflow"`

---

### Task 6: Build the RAG pipeline for code and incident history

**Files:**
- Create: `src/sre_agent/rag/__init__.py`
- Create: `src/sre_agent/rag/loaders.py`
- Create: `src/sre_agent/rag/chunking.py`
- Create: `src/sre_agent/rag/indexer.py`
- Create: `src/sre_agent/rag/retriever.py`
- Create: `src/sre_agent/rag/store.py`
- Create: `src/sre_agent/rag/source_fetcher.py`
- Modify: `src/sre_agent/storage/incidents.py`
- Modify: `src/sre_agent/tools/repository.py`
- Modify: `src/sre_agent/tools/incidents.py`
- Create: `tests/test_rag_indexer.py`
- Create: `tests/test_rag_retriever.py`
- Create: `tests/test_source_fetcher.py`

**Step 1: Write the failing RAG tests**

- Add tests for:
  - source code chunking with line offsets
  - indexing incident snapshots from JSONL
  - filtering by file suffix and path glob
  - retrieving the top-k snippets with metadata
  - source fetcher behaviour for local, git, and fallback modes

**Step 2: Implement source fetching before indexing**

- Add `src/sre_agent/rag/source_fetcher.py` with three modes:
  - local directory via `CODEBASE_PATH`
  - read-only git clone or refresh via `CODEBASE_GIT_URL` and `CODEBASE_GIT_BRANCH`
  - fallback grep-style lookup when a vector store is unavailable
- Cache fetched sources in `CODEBASE_CACHE_PATH`.
- Keep source fetching optional so the agent still runs without a checked-out Java repository.

**Step 3: Implement a small indexing pipeline**

- Index:
  - Java source files from the resolved codebase path
  - stored incident snapshots from `INCIDENT_STORE_PATH`
- Persist chunk metadata with file path, start line, end line, trace ID, and incident code where available.

**Step 4: Implement retrieval adapters for the graph**

- Add code retrieval for source snippets.
- Add incident retrieval for similar historical failures.
- Return small structured results that the graph can cite in the report.

**Step 5: Preserve offline safety**

- If the vector store is not configured, return structured unavailable results.
- Keep direct `search_codebase` grep-style lookup as a fallback.

**Step 6: Run the focused tests**

Run: `pytest tests/test_rag_indexer.py tests/test_rag_retriever.py tests/test_source_fetcher.py tests/test_repository_tools.py -v`

Expected:
- Source and incident retrieval work.
- Source fetching supports local and git-backed codebases.
- Fallback grep search still works.

**Step 7: Commit**

Run: `git add src/sre_agent/rag src/sre_agent/storage/incidents.py src/sre_agent/tools/repository.py src/sre_agent/tools/incidents.py tests/test_rag_indexer.py tests/test_rag_retriever.py tests/test_source_fetcher.py`

Run: `git commit -m "feat: add code and incident retrieval pipeline"`

---

### Task 7: Add short-term and long-term memory

**Files:**
- Create: `src/sre_agent/memory/__init__.py`
- Create: `src/sre_agent/memory/short_term.py`
- Create: `src/sre_agent/memory/long_term.py`
- Create: `src/sre_agent/memory/summaries.py`
- Modify: `src/sre_agent/graph/state.py`
- Modify: `src/sre_agent/graph/nodes.py`
- Create: `tests/test_memory.py`

**Step 1: Write the failing memory tests**

- Add tests for:
  - sliding-window short-term memory
  - long-term summary persistence
  - similarity recall from prior incidents
  - graph state including memory hits in the final report

**Step 2: Implement short-term memory**

- Keep a compact in-process memory of the current cycle and the recent cycles.
- Limit token growth by storing summaries, not raw logs.

**Step 3: Implement long-term memory**

- Store summarised incidents and successful remediations in pgvector-backed tables.
- Keep schema and SQL isolated in one module.

**Step 4: Feed memory into the graph**

- Add a retrieval step before final report synthesis.
- Include memory hits in the report payload for auditability.

**Step 5: Run the focused tests**

Run: `pytest tests/test_memory.py tests/test_graph_workflow.py -v`

Expected:
- Short-term and long-term memory paths both work.
- Graph output records memory usage.

**Step 6: Commit**

Run: `git add src/sre_agent/memory src/sre_agent/graph/state.py src/sre_agent/graph/nodes.py tests/test_memory.py`

Run: `git commit -m "feat: add tiered agent memory"`

---

### Task 8: Rewrite monitor orchestration around cycle aggregation

**Files:**
- Modify: `src/sre_agent/monitor/service.py`
- Modify: `src/sre_agent/core/agent.py`
- Modify: `src/sre_agent/storage/incidents.py`
- Modify: `src/sre_agent/notify/webhook.py`
- Create: `src/sre_agent/reporting/__init__.py`
- Create: `src/sre_agent/reporting/formatter.py`
- Create: `tests/test_monitor_service.py`
- Create: `tests/test_reporting.py`

**Step 1: Write the failing orchestration tests**

- Keep tests for the current legacy path.
- Add tests for the new autonomous path.
- Add a test that host pressure, JVM errors, and workflow failures are merged into one correlated incident when they land in the same time window or share an error signature.
- Add a test that `GRAPH_ENABLE_AUTONOMOUS_LOOP` switches between both paths cleanly.

**Step 2: Preserve the current legacy path**

- Split `run_cycle()` into:
  - `_run_legacy_cycle()`
  - `_run_autonomous_cycle()`
- Route by `GRAPH_ENABLE_AUTONOMOUS_LOOP`.
- Keep the existing legacy behaviour intact until the autonomous path is fully verified.

**Step 3: Gather one cycle observation first in the autonomous path**

- Collect host, container, JVM, business, and metric evidence before diagnosis.
- Create one `CycleObservation` object from the whole run.

**Step 4: Send the full cycle to the graph**

- Let the graph decide whether the cycle contains:
  - one multi-signal incident
  - multiple unrelated incidents
  - no actionable incident

**Step 5: Format structured reports**

- Add JSON and human-readable report builders.
- Include fields from the upgrade document, such as:
  - `incident_summary`
  - `root_cause`
  - `evidence`
  - `suggested_actions`
  - `code_change_suggestions`
  - `react_steps`
  - `tools_called`
  - `health_score`

**Step 6: Update notification payloads**

- Send compact summaries to webhook targets.
- Persist the full autonomous report locally.

**Step 7: Run the focused tests**

Run: `pytest tests/test_monitor_service.py tests/test_reporting.py -v`

Expected:
- Legacy monitoring still works.
- Autonomous monitoring is cycle-aware.
- Structured reports are stored and rendered correctly.

**Step 8: Commit**

Run: `git add src/sre_agent/monitor/service.py src/sre_agent/core/agent.py src/sre_agent/storage/incidents.py src/sre_agent/notify/webhook.py src/sre_agent/reporting tests/test_monitor_service.py tests/test_reporting.py`

Run: `git commit -m "feat: add cycle-level autonomous orchestration"`

---

### Task 9: Extend the CLI and operational entrypoints

**Files:**
- Modify: `src/sre_agent/cli/main.py`
- Modify: `src/sre_agent/run.py`
- Modify: `README.md`
- Create: `tests/test_cli.py`

**Step 1: Write the failing CLI tests**

- Add tests for new commands and flags:
  - `sre-agent monitor --autonomous`
  - `sre-agent diagnose --autonomous`
  - `sre-agent rag index`
  - `sre-agent eval ragas`
  - `sre-agent trace test`

**Step 2: Keep the current entrypoints stable**

- Existing commands should continue to work.
- Autonomous mode should be an opt-in switch until the graph path is stable.

**Step 3: Add indexing and evaluation subcommands**

- Add CLI entrypoints to:
  - build the RAG index
  - run evaluation against a golden dataset
  - send a tracing smoke event

**Step 4: Update README usage examples**

- Document old mode and autonomous mode side by side.

**Step 5: Run the focused tests**

Run: `pytest tests/test_cli.py -v`

Expected:
- New commands parse correctly.
- Backwards-compatible commands still work.

**Step 6: Commit**

Run: `git add src/sre_agent/cli/main.py src/sre_agent/run.py README.md tests/test_cli.py`

Run: `git commit -m "feat: add autonomous CLI commands"`

---

### Task 10: Add Langfuse tracing and RAGAS evaluation

**Files:**
- Create: `src/sre_agent/evaluation/__init__.py`
- Create: `src/sre_agent/evaluation/ragas_runner.py`
- Create: `src/sre_agent/observability/langfuse_client.py`
- Create: `tests/test_ragas_runner.py`
- Create: `tests/test_langfuse_client.py`
- Create: `data/eval/golden_dataset.sample.json`
- Modify: `README.md`
- Modify: `DEVELOPMENT.md`

**Step 1: Write the failing tracing and evaluation tests**

- Add tests that verify:
  - tracing config is optional
  - missing Langfuse credentials do not break diagnosis
  - a sample golden dataset can be loaded and validated
  - the RAGAS runner is not wired into the production monitor loop

**Step 2: Implement Langfuse tracing**

- Wrap Langfuse setup in a small client module.
- Attach callbacks only when credentials are configured.
- Default to a hosted Langfuse endpoint, not a self-hosted service on the 2 core, 2 GB production server.

**Step 3: Implement the RAGAS runner**

- Load a JSON dataset from disk.
- Run the selected metrics from the upgrade document.
- Emit a compact summary for CLI and CI use.
- Treat RAGAS evaluation as CI or local developer workflow, not as a production-host workload.

**Step 4: Provide a sample dataset**

- Add a small checked-in example that documents the expected schema.

**Step 5: Run the focused tests**

Run: `pytest tests/test_ragas_runner.py tests/test_langfuse_client.py -v`

Expected:
- Evaluation and tracing paths remain optional and testable.
- No production monitoring path depends on local RAGAS execution.

**Step 6: Commit**

Run: `git add src/sre_agent/evaluation src/sre_agent/observability/langfuse_client.py tests/test_ragas_runner.py tests/test_langfuse_client.py data/eval/golden_dataset.sample.json README.md DEVELOPMENT.md`

Run: `git commit -m "feat: add tracing and evaluation support"`

---

### Task 11: Run end-to-end validation and clean-up

**Files:**
- Modify: `README.md`
- Modify: `RELEASE.md`
- Modify: `docs/浼樺寲鏂瑰悜.md`
- Modify: `docs/椤圭洰淇敼鏂瑰悜.md`

**Step 1: Run the focused test suites first**

Run: `pytest tests/test_settings.py tests/test_cycle_models.py tests/test_tool_registry.py tests/test_prometheus_client.py tests/test_prometheus_tools.py tests/test_graph_workflow.py tests/test_rag_indexer.py tests/test_memory.py tests/test_monitor_service.py tests/test_cli.py tests/test_ragas_runner.py -v`

Expected:
- All new autonomous-agent tests pass.

**Step 2: Run the full test suite**

Run: `pytest -v`

Expected:
- The whole repository passes.

**Step 3: Run smoke commands**

Run: `python -m sre_agent.run`

Run: `python -m sre_agent.cli.main monitor --once`

Run: `python -m sre_agent.cli.main diagnose --autonomous`

Expected:
- Each command completes cleanly.
- Missing optional integrations degrade gracefully.

**Step 4: Update release notes and docs**

- Document:
  - autonomous mode
  - Prometheus prerequisites
  - RAG indexing flow
  - memory store requirements
  - tracing and evaluation flow

**Step 5: Commit**

Run: `git add README.md RELEASE.md docs/浼樺寲鏂瑰悜.md docs/椤圭洰淇敼鏂瑰悜.md`

Run: `git commit -m "docs: document autonomous agent upgrade"`

---

## Acceptance criteria

- The project supports an opt-in LangGraph autonomous mode without breaking the current monitor workflow.
- The legacy monitor path remains available behind `GRAPH_ENABLE_AUTONOMOUS_LOOP=false` until the new path is proven.
- One monitoring cycle can correlate host, container, JVM, business, and Prometheus signals before diagnosis.
- The first correlation pass works with time windows and shared error signatures, with deeper semantic correlation left to the graph.
- The agent can call tools dynamically and record every ReAct step.
- The agent can retrieve relevant source snippets and similar historical incidents.
- The agent can fetch external Java source code from a mounted path or a read-only git source.
- The agent can persist compact short-term and long-term memory.
- The final report includes structured root cause, evidence, code suggestions, tools called, and a health score.
- Prometheus, pgvector, Langfuse, and RAGAS integrations are optional and fail safely.
- RAGAS does not run as part of the production monitoring loop on the constrained host.
- Deployment and usage instructions are documented for the single-host Docker Compose environment.

## Out of scope for this implementation pass

- A front-end web UI.
- Arbitrary shell execution by the LLM.
- Non-whitelisted auto-remediation actions.
- Multi-host distributed scheduling.

## Suggested execution order

1. Task 1
2. Task 2
3. Task 3 phase 1
4. Task 5
5. Task 4
6. Task 3 phase 2
7. Task 6 and Task 7
8. Task 8
9. Task 9 and Task 10
10. Task 11

This order lets the graph skeleton run with stub tools first, then introduces live integrations and only rewrites the service orchestration after the autonomous path has a safety net.


