"""Shared filesystem paths for runtime configuration."""

from pathlib import Path

from platformdirs import user_config_dir
from dotenv import load_dotenv

APP_NAME = "sre-agent"
CLI_CONFIG_FILENAME = "config.json"
ENV_FILENAME = ".env"


def config_dir() -> Path:
    """Return the user configuration directory.

    Returns:
        The user configuration directory path.
    """
    return Path(user_config_dir(APP_NAME))


def cli_config_path() -> Path:
    """Return the CLI configuration file path.

    Returns:
        The CLI configuration file path.
    """
    return config_dir() / CLI_CONFIG_FILENAME


def env_path() -> Path:
    """Return the user env file path.

    Returns:
        The user env file path.
    """
    return config_dir() / ENV_FILENAME


def system_env_path() -> Path:
    """Return the system env file path."""

    return Path("/etc/sre-agent.env")


def project_root() -> Path:
    """Return the project root when running from source."""

    return Path(__file__).resolve().parents[3]


def project_env_path() -> Path:
    """Return the project env file path."""

    return project_root() / ENV_FILENAME


def env_candidates() -> list[Path]:
    """Return candidate env files in load order."""

    return [project_env_path(), env_path(), system_env_path()]


def load_runtime_env() -> list[Path]:
    """Load env files that exist and return the loaded paths."""

    loaded_paths: list[Path] = []
    for candidate in env_candidates():
        if not candidate.exists():
            continue
        load_dotenv(candidate, override=False)
        loaded_paths.append(candidate)
    return loaded_paths
