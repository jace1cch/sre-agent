"""Tests for runtime settings."""

from sre_agent.core.settings import AgentSettings


def test_log_clean_paths_are_parsed_from_csv() -> None:
    """CSV log cleanup paths are parsed correctly."""

    settings = AgentSettings(_env_file=None, LOG_CLEAN_PATHS=" /var/log/app , /tmp/logs ")
    assert settings.log_clean_paths == ["/var/log/app", "/tmp/logs"]


def test_default_container_name_is_app() -> None:
    """The default container name stays stable."""

    settings = AgentSettings(_env_file=None)
    assert settings.app_container_name == "app"
    assert settings.monitored_container_names() == ["app"]


def test_container_names_are_parsed_from_csv() -> None:
    """CSV container targets are parsed in order."""

    settings = AgentSettings(
        _env_file=None,
        APP_CONTAINER_NAME="api",
        APP_CONTAINER_NAMES="api, worker , console",
    )
    assert settings.monitored_container_names() == ["api", "worker", "console"]


def test_container_names_do_not_include_default_placeholder() -> None:
    """Container lists ignore the default single-container placeholder."""

    settings = AgentSettings(
        _env_file=None,
        APP_CONTAINER_NAMES="worker,console",
    )
    assert settings.monitored_container_names() == ["worker", "console"]


def test_default_model_provider_matches_deepseek() -> None:
    """The default OpenAI-compatible provider points to DeepSeek."""

    settings = AgentSettings(_env_file=None)
    assert settings.model == "deepseek-chat"
    assert settings.openai_base_url == "https://api.deepseek.com"


def test_graph_settings_default_to_autonomous_mode() -> None:
    """Graph settings default to the autonomous runtime."""

    settings = AgentSettings(_env_file=None)
    assert settings.graph_enable_autonomous_loop is True
    assert settings.graph_max_steps == 4
    assert settings.codebase_fetch_mode == "local"
    assert settings.codebase_retrieval_mode == "hybrid"


def test_legacy_local_text_mode_maps_to_exact_only() -> None:
    """Legacy local text retrieval config stays backwards compatible."""

    settings = AgentSettings(_env_file=None, CODEBASE_RETRIEVAL_MODE="local_text")

    assert settings.codebase_retrieval_mode == "exact_only"
