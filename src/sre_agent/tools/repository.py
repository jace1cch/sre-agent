"""Repository search runtime tools."""

from sre_agent.core.settings import AgentSettings
from sre_agent.rag import CodeRetriever


class RepositoryTools:
    """Repository-backed tool implementations."""

    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.retriever = CodeRetriever(settings)

    def search_codebase(self, arguments: dict[str, object]) -> dict[str, object]:
        """Search the configured codebase for a query string."""

        query = str(arguments.get("query") or "").strip()
        return self.retriever.search(query)
