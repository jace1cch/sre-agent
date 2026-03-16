"""Repository search runtime tools."""

from pathlib import Path

from sre_agent.core.settings import AgentSettings
from sre_agent.tools.common import completed_response, configured_codebase_path, unavailable_response

_ALLOWED_SUFFIXES = {".java", ".kt", ".groovy", ".xml", ".yml", ".yaml", ".properties", ".py"}
_SKIPPED_PARTS = {".git", ".venv", "node_modules", "dist", "build", "target", "__pycache__"}


class RepositoryTools:
    """Repository-backed tool implementations."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings

    def search_codebase(self, arguments: dict[str, object]) -> dict[str, object]:
        """Search the configured codebase for a query string."""

        root = configured_codebase_path(self.settings)
        if not root:
            return unavailable_response(
                "No repository or codebase path is configured.",
                source="repository",
            )

        base = Path(root)
        if not base.exists():
            return unavailable_response(
                f"Configured codebase path {base} does not exist.",
                source="repository",
            )

        query = str(arguments.get("query") or "").strip()
        if not query:
            return unavailable_response(
                "No repository search query was provided.",
                source="repository",
            )

        results: list[dict[str, object]] = []
        lowered_query = query.lower()
        for path in base.rglob("*"):
            if len(results) >= 5:
                break
            if not path.is_file():
                continue
            if any(part in _SKIPPED_PARTS for part in path.parts):
                continue
            if path.suffix.lower() not in _ALLOWED_SUFFIXES:
                continue
            try:
                lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if lowered_query not in line.lower():
                    continue
                results.append(
                    {
                        "file_path": str(path),
                        "line_number": line_number,
                        "line": line.strip(),
                    }
                )
                break

        if not results:
            return unavailable_response(
                f"No code matches were found for query {query}.",
                source="repository",
            )
        return completed_response(
            f"Found {len(results)} code matches for query {query}.",
            data={"matches": results},
            source="repository",
        )