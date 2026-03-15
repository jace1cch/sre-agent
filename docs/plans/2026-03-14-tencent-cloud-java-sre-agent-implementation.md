# Tencent Cloud Java SRE Agent Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace the AWS-centric diagnosis flow with a lean single-host MVP that monitors a Tencent Cloud CVM, inspects a Dockerised Java application, sends webhook alerts, and supports safe low-risk remediation.

**Architecture:** Keep the existing `pydantic-ai` diagnosis core, but move anomaly detection to deterministic local detectors. Introduce a lightweight monitor service that gathers host, Docker, JVM, and business-log evidence, stores incident snapshots locally, optionally calls the LLM for a root cause report, and sends the result through a generic webhook.

**Tech Stack:** Python 3.13, Click, pydantic, pydantic-settings, pydantic-ai, Docker CLI, standard library HTTP and filesystem tools.

---

### Task 1: Simplify runtime configuration

**Files:**
- Modify: `src/sre_agent/core/settings.py`
- Modify: `src/sre_agent/config/paths.py`
- Test: `tests/test_settings.py`

**Step 1: Define the new flat configuration model**

- Remove AWS, GitHub, and Slack-specific required settings from the main runtime path.
- Add single-host settings for:
  - model access
  - Docker container name
  - polling interval
  - host thresholds
  - JVM log thresholds
  - business thresholds
  - webhook URL and provider
  - remediation settings
  - incident storage path

**Step 2: Keep env loading compatible**

- Continue to load `.env` from `src/sre_agent/config/paths.py`.
- Add parsing for comma-separated log cleanup paths.

**Step 3: Add focused tests**

- Verify defaults load.
- Verify comma-separated cleanup paths are parsed.

### Task 2: Replace the diagnosis prompt flow

**Files:**
- Modify: `src/sre_agent/core/agent.py`
- Modify: `src/sre_agent/core/prompts.py`
- Modify: `src/sre_agent/core/prompts/system_prompt.txt`
- Modify: `src/sre_agent/core/prompts/diagnosis_prompt.txt`

**Step 1: Remove MCP tool dependency from the main agent path**

- Build a plain structured-output agent with no CloudWatch, Slack, or GitHub tools.

**Step 2: Introduce incident-based diagnosis**

- Add a new `diagnose_incident()` entrypoint that accepts structured evidence.
- Keep a compatibility shim for `diagnose_error()` so the repo still imports cleanly.

**Step 3: Add a deterministic fallback diagnosis**

- If no model key is configured, or the model call fails, generate a concise evidence-based fallback report.

### Task 3: Add local detector modules

**Files:**
- Create: `src/sre_agent/detectors/__init__.py`
- Create: `src/sre_agent/detectors/host.py`
- Create: `src/sre_agent/detectors/docker.py`
- Create: `src/sre_agent/detectors/java.py`
- Create: `src/sre_agent/detectors/business.py`
- Create: `src/sre_agent/utils/__init__.py`
- Create: `src/sre_agent/utils/shell.py`
- Modify: `src/sre_agent/core/models.py`
- Test: `tests/test_host_detector.py`
- Test: `tests/test_java_detector.py`
- Test: `tests/test_business_detector.py`

**Step 1: Add shared incident and evidence models**

- Extend the core models with:
  - host snapshot
  - container snapshot
  - monitor finding
  - evidence bundle
  - incident
  - remediation action result

**Step 2: Implement host checks**

- Detect disk pressure, low available memory, and CPU or load pressure.

**Step 3: Implement Docker checks**

- Inspect container status, restart count, exit code, and `OOMKilled` state.
- Fetch recent container logs.

**Step 4: Implement JVM and business log checks**

- Detect `ERROR` bursts, OOM signals, and Full GC signals.
- Parse structured business logs for token anomalies, stuck workflows, tool failures, and workflow failure rate.

### Task 4: Add notification, storage, and remediation layers

**Files:**
- Create: `src/sre_agent/notify/__init__.py`
- Create: `src/sre_agent/notify/webhook.py`
- Create: `src/sre_agent/storage/__init__.py`
- Create: `src/sre_agent/storage/incidents.py`
- Create: `src/sre_agent/actions/__init__.py`
- Create: `src/sre_agent/actions/playbooks.py`
- Create: `src/sre_agent/actions/executor.py`

**Step 1: Implement a generic webhook notifier**

- Support at least `generic` and `feishu` payload formats.

**Step 2: Persist incident snapshots locally**

- Append incident and diagnosis JSON to a local JSONL file.

**Step 3: Add safe low-risk playbooks**

- Clean old logs from configured directories.
- Restart the app container after OOM.
- Add a generic stuck-workflow cancellation hook guarded by config.

### Task 5: Add the monitor orchestration service

**Files:**
- Create: `src/sre_agent/monitor/__init__.py`
- Create: `src/sre_agent/monitor/service.py`

**Step 1: Orchestrate detector execution**

- Gather host, container, JVM, and business evidence in one service.

**Step 2: Build an incident when findings exist**

- Derive severity from detector outputs.
- Capture thread dumps only when a JVM alert is present.

**Step 3: Wire diagnosis, remediation, storage, and notification**

- Diagnose the incident.
- Optionally execute remediation when enabled.
- Store the incident.
- Send the alert.

### Task 6: Replace the CLI with MVP commands

**Files:**
- Modify: `src/sre_agent/cli/main.py`
- Modify: `src/sre_agent/run.py`
- Modify: `src/sre_agent/__init__.py`

**Step 1: Replace the interactive default**

- Make the CLI default to help text, not the AWS-oriented interactive shell.

**Step 2: Add the MVP commands**

- `sre-agent monitor`
- `sre-agent diagnose`
- `sre-agent test-notify`

**Step 3: Keep the direct module entrypoint useful**

- Make `python -m sre_agent.run` perform a single diagnosis cycle against the configured container.

### Task 7: Validate the first MVP slice

**Files:**
- Test: `tests/test_settings.py`
- Test: `tests/test_host_detector.py`
- Test: `tests/test_java_detector.py`
- Test: `tests/test_business_detector.py`

**Step 1: Run focused tests**

Run:

```bash
pytest tests/test_settings.py tests/test_host_detector.py tests/test_java_detector.py tests/test_business_detector.py -v
```

Expected:

- All new detector and settings tests pass.

**Step 2: Run a CLI smoke check**

Run:

```bash
python -m sre_agent.run
```

Expected:

- The command completes cleanly.
- If Docker or a webhook is not configured, it degrades gracefully.
