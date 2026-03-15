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


def test_default_model_provider_matches_deepseek() -> None:
    """The default OpenAI-compatible provider points to DeepSeek."""

    settings = AgentSettings(_env_file=None)
    assert settings.model == "deepseek-chat"
    assert settings.openai_base_url == "https://api.deepseek.com"
