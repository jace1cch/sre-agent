"""Runtime settings for the SRE Agent."""

from functools import lru_cache
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sre_agent.config.paths import env_candidates, load_runtime_env


def _parse_csv_list(value: object) -> list[str]:
    """Parse a CSV-like value into a list of non-empty strings."""

    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return []


def _deduplicate_strings(values: list[str]) -> list[str]:
    """Keep insertion order while removing duplicates."""

    return list(dict.fromkeys(values))


class AgentSettings(BaseModel):
    """Main runtime configuration."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    openai_api_key: str | None = Field(default=None, alias="OPENAI_API_KEY")
    openai_base_url: str = Field(
        default="https://api.deepseek.com",
        alias="OPENAI_BASE_URL",
    )
    model: str = Field(default="deepseek-chat", alias="MODEL")
    repository_path: str | None = Field(default=None, alias="REPOSITORY_PATH")
    prometheus_base_url: str | None = Field(default=None, alias="PROMETHEUS_BASE_URL")
    prometheus_timeout_seconds: int = Field(default=5, alias="PROMETHEUS_TIMEOUT_SECONDS")
    prometheus_step_seconds: int = Field(default=60, alias="PROMETHEUS_STEP_SECONDS")
    graph_enable_autonomous_loop: bool = Field(
        default=False,
        alias="GRAPH_ENABLE_AUTONOMOUS_LOOP",
    )
    graph_max_steps: int = Field(default=4, alias="GRAPH_MAX_STEPS")
    codebase_path: str | None = Field(default=None, alias="CODEBASE_PATH")
    codebase_fetch_mode: Literal["local", "git", "disabled"] = Field(
        default="local",
        alias="CODEBASE_FETCH_MODE",
    )
    codebase_git_url: str | None = Field(default=None, alias="CODEBASE_GIT_URL")
    codebase_git_branch: str = Field(default="main", alias="CODEBASE_GIT_BRANCH")
    codebase_cache_path: str = Field(
        default=".cache/codebase",
        alias="CODEBASE_CACHE_PATH",
    )

    check_interval_seconds: int = Field(default=60, alias="CHECK_INTERVAL_SECONDS")
    host_disk_path: str = Field(default="/", alias="HOST_DISK_PATH")
    cpu_percent_threshold: float = Field(default=75.0, alias="CPU_PERCENT_THRESHOLD")
    memory_available_threshold_mb: int = Field(
        default=384,
        alias="MEMORY_AVAILABLE_THRESHOLD_MB",
    )
    disk_threshold_percent: float = Field(default=85.0, alias="DISK_THRESHOLD_PERCENT")
    load_threshold_per_core: float = Field(default=0.85, alias="LOAD_THRESHOLD_PER_CORE")

    app_container_name: str = Field(default="app", alias="APP_CONTAINER_NAME")
    app_container_names: list[str] = Field(default_factory=list, alias="APP_CONTAINER_NAMES")
    app_log_since_seconds: int = Field(default=300, alias="APP_LOG_SINCE_SECONDS")
    restart_threshold: int = Field(default=0, alias="CONTAINER_RESTART_THRESHOLD")
    error_burst_threshold: int = Field(default=5, alias="ERROR_BURST_THRESHOLD")
    full_gc_threshold: int = Field(default=1, alias="FULL_GC_THRESHOLD")
    java_diag_mode: Literal["jstack", "jcmd", "sigquit"] = Field(
        default="sigquit",
        alias="JAVA_DIAG_MODE",
    )

    workflow_timeout_seconds: int = Field(default=300, alias="WORKFLOW_TIMEOUT_SECONDS")
    workflow_failure_rate_threshold: float = Field(
        default=0.15,
        alias="WORKFLOW_FAILURE_RATE_THRESHOLD",
    )
    token_anomaly_threshold: int = Field(default=20000, alias="TOKEN_ANOMALY_THRESHOLD")
    tool_failure_rate_threshold: float = Field(
        default=0.2,
        alias="TOOL_FAILURE_RATE_THRESHOLD",
    )

    webhook_url: str | None = Field(default=None, alias="WEBHOOK_URL")
    webhook_provider: Literal["generic", "feishu"] = Field(
        default="generic",
        alias="WEBHOOK_PROVIDER",
    )
    webhook_timeout_seconds: int = Field(default=10, alias="WEBHOOK_TIMEOUT_SECONDS")

    auto_remediate: bool = Field(default=False, alias="AUTO_REMEDIATE")
    log_retention_days: int = Field(default=30, alias="LOG_RETENTION_DAYS")
    log_clean_paths: list[str] = Field(default_factory=list, alias="LOG_CLEAN_PATHS")
    workflow_cancel_url: str | None = Field(default=None, alias="WORKFLOW_CANCEL_URL")
    workflow_cancel_token: str | None = Field(default=None, alias="WORKFLOW_CANCEL_TOKEN")

    incident_store_path: str = Field(
        default="data/incidents.jsonl",
        alias="INCIDENT_STORE_PATH",
    )

    @field_validator("log_clean_paths", mode="before")
    @classmethod
    def _parse_log_clean_paths(cls, value: object) -> list[str]:
        return _parse_csv_list(value)

    @field_validator("app_container_names", mode="before")
    @classmethod
    def _parse_app_container_names(cls, value: object) -> list[str]:
        return _parse_csv_list(value)

    def monitored_container_names(self) -> list[str]:
        """Return the configured container targets in monitoring order."""

        if not self.app_container_names:
            return [self.app_container_name]

        names = list(self.app_container_names)
        should_prepend_single = "app_container_name" in self.model_fields_set and (
            self.app_container_name != "app" or self.app_container_name in names
        )
        if should_prepend_single and self.app_container_name:
            names.insert(0, self.app_container_name)
        return _deduplicate_strings(names)


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, raw_value = line.split("=", maxsplit=1)
        values[key.strip()] = raw_value.strip().strip("\"").strip("'")
    return values


@lru_cache(maxsize=1)
def get_settings() -> AgentSettings:
    """Load and cache the agent configuration."""

    load_runtime_env()
    payload: dict[str, str] = {}
    for candidate in env_candidates():
        if not candidate.exists():
            continue
        payload.update(_read_env_file(candidate))
    payload.update(os.environ)
    return AgentSettings(**payload)

