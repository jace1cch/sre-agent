"""Hybrid operational retrievers for code and incident history."""

from pathlib import Path

from sre_agent.core.settings import AgentSettings, get_settings
from sre_agent.rag.chunking import chunk_incidents_jsonl, iter_code_chunks
from sre_agent.rag.exact_search import exact_code_search, exact_text_search
from sre_agent.rag.fusion import rrf_merge
from sre_agent.rag.models import RetrievalChunk, RetrievalMatch
from sre_agent.rag.vector_store import SQLiteVecIndex
from sre_agent.tools.common import configured_codebase_path


class CodeRetriever:
    """Retrieve code context with exact-first hybrid search."""

    def __init__(self, settings: AgentSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.vector_index = SQLiteVecIndex(self.settings)

    def is_available(self) -> bool:
        """Return whether any code retrieval backend can run."""

        if self.settings.codebase_retrieval_mode == "disabled":
            return False
        root = configured_codebase_path(self.settings)
        return bool(root and Path(root).exists())

    def search(self, query: str, limit: int | None = None) -> dict[str, object]:
        """Search the configured codebase for a query string."""

        root = configured_codebase_path(self.settings)
        if self.settings.codebase_retrieval_mode == "disabled":
            return _unavailable_response("Code retrieval is disabled.", source="repository")
        if not root:
            return _unavailable_response("No repository or codebase path is configured.", source="repository")

        base = Path(root)
        if not base.exists():
            return _unavailable_response(f"Configured codebase path {base} does not exist.", source="repository")
        cleaned_query = query.strip()
        if not cleaned_query:
            return _unavailable_response("No repository search query was provided.", source="repository")

        result_limit = limit or self.settings.rag_result_limit
        exact_matches = exact_code_search(
            cleaned_query,
            base,
            top_k=self.settings.rag_exact_top_k,
            context_lines=self.settings.rag_context_lines,
        )
        vector_matches = self._vector_matches(
            corpus="code",
            source_path=str(base),
            chunks=lambda: iter_code_chunks(base),
            query=cleaned_query,
        )
        fused_matches = self._merge_matches(exact_matches, vector_matches, top_k=result_limit)
        if not fused_matches:
            return _unavailable_response(
                f"No code matches were found for query {cleaned_query}.",
                backend=self._backend_label(vector_matches),
                method="hybrid",
                source="repository",
            )

        return {
            "status": "completed",
            "summary": (
                f"Found {len(fused_matches)} code matches for query {cleaned_query} "
                f"using {self._backend_label(vector_matches)} retrieval."
            ),
            "data": {
                "backend": self._backend_label(vector_matches),
                "method": "rrf",
                "exact_matches": [_match_payload(match) for match in exact_matches[:result_limit]],
                "vector_matches": [_match_payload(match) for match in vector_matches[:result_limit]],
                "matches": [_match_payload(match) for match in fused_matches],
            },
            "source": "repository",
        }

    def _vector_matches(
        self,
        *,
        corpus: str,
        source_path: str,
        chunks,
        query: str,
    ) -> list[RetrievalMatch]:
        mode = self.settings.codebase_retrieval_mode
        if mode in {"disabled", "exact_only"}:
            return []
        return self.vector_index.search(
            corpus=corpus,
            source_path=source_path,
            chunks=chunks(),
            query=query,
            top_k=self.settings.rag_vector_top_k,
        )

    def _merge_matches(
        self,
        exact_matches: list[RetrievalMatch],
        vector_matches: list[RetrievalMatch],
        *,
        top_k: int,
    ) -> list[RetrievalMatch]:
        mode = self.settings.codebase_retrieval_mode
        if mode == "vector":
            return vector_matches[:top_k] or exact_matches[:top_k]
        if mode == "exact_only":
            return exact_matches[:top_k]
        if vector_matches:
            return rrf_merge(
                exact_matches,
                vector_matches,
                exact_weight=self.settings.rag_exact_weight,
                top_k=top_k,
            )
        return exact_matches[:top_k]

    def _backend_label(self, vector_matches: list[RetrievalMatch]) -> str:
        if self.settings.codebase_retrieval_mode == "exact_only":
            return "exact_only"
        if vector_matches:
            return "hybrid"
        if self.vector_index.is_available():
            return "hybrid"
        return "exact_only"


class IncidentRetriever:
    """Retrieve similar incidents with exact-first hybrid search."""

    def __init__(self, settings: AgentSettings | None = None) -> None:
        self.settings = settings or get_settings()
        self.vector_index = SQLiteVecIndex(self.settings)

    def search(self, query: str, limit: int | None = None) -> dict[str, object]:
        """Search stored incident history for similar incidents."""

        path = Path(self.settings.incident_store_path)
        if not path.exists():
            return _unavailable_response("No incident history is available yet.", source="incident_store")

        cleaned_query = query.strip()
        if not cleaned_query:
            return _unavailable_response("No incident recall query was provided.", source="incident_store")

        chunks = chunk_incidents_jsonl(path)
        if not chunks:
            return _unavailable_response(
                "Incident history exists but contains no retrievable records.",
                source="incident_store",
            )

        result_limit = limit or self.settings.rag_result_limit
        exact_matches = exact_text_search(
            cleaned_query,
            chunks,
            top_k=self.settings.rag_exact_top_k,
        )
        vector_matches = self._vector_matches(
            source_path=str(path),
            chunks=chunks,
            query=cleaned_query,
        )
        merged_matches = self._merge_matches(exact_matches, vector_matches, top_k=result_limit)
        if not merged_matches:
            return _unavailable_response(
                f"No similar incidents were found for query {cleaned_query}.",
                backend=self._backend_label(vector_matches),
                method="hybrid",
                source="incident_store",
            )

        return {
            "status": "completed",
            "summary": (
                f"Found {len(merged_matches)} similar incidents for query {cleaned_query} "
                f"using {self._backend_label(vector_matches)} retrieval."
            ),
            "data": {
                "backend": self._backend_label(vector_matches),
                "method": "rrf",
                "matches": [_incident_match_payload(match) for match in merged_matches],
            },
            "source": "incident_store",
        }

    def _vector_matches(
        self,
        *,
        source_path: str,
        chunks: list[RetrievalChunk],
        query: str,
    ) -> list[RetrievalMatch]:
        mode = self.settings.codebase_retrieval_mode
        if mode in {"disabled", "exact_only"}:
            return []
        return self.vector_index.search(
            corpus="incident_history",
            source_path=source_path,
            chunks=chunks,
            query=query,
            top_k=self.settings.rag_vector_top_k,
        )

    def _merge_matches(
        self,
        exact_matches: list[RetrievalMatch],
        vector_matches: list[RetrievalMatch],
        *,
        top_k: int,
    ) -> list[RetrievalMatch]:
        mode = self.settings.codebase_retrieval_mode
        if mode == "vector":
            return vector_matches[:top_k] or exact_matches[:top_k]
        if mode == "exact_only":
            return exact_matches[:top_k]
        if vector_matches:
            return rrf_merge(
                exact_matches,
                vector_matches,
                exact_weight=self.settings.rag_exact_weight,
                top_k=top_k,
            )
        return exact_matches[:top_k]

    def _backend_label(self, vector_matches: list[RetrievalMatch]) -> str:
        if self.settings.codebase_retrieval_mode == "exact_only":
            return "exact_only"
        if vector_matches:
            return "hybrid"
        if self.vector_index.is_available():
            return "hybrid"
        return "exact_only"


def _match_payload(match: RetrievalMatch) -> dict[str, object]:
    return {
        "id": match.chunk.chunk_id,
        "file_path": match.chunk.file_path,
        "start_line": match.chunk.start_line,
        "end_line": match.chunk.end_line,
        "content": match.chunk.content,
        "strategy": match.strategy,
        "score": round(match.score, 6),
        "metadata": match.chunk.metadata,
    }


def _incident_match_payload(match: RetrievalMatch) -> dict[str, object]:
    payload = _match_payload(match)
    metadata = dict(match.chunk.metadata)
    payload["incident"] = metadata.get("incident")
    payload["diagnosis"] = metadata.get("diagnosis")
    return payload


def _unavailable_response(
    summary: str,
    *,
    backend: str | None = None,
    method: str | None = None,
    source: str,
) -> dict[str, object]:
    data: dict[str, object] = {}
    if backend is not None:
        data["backend"] = backend
    if method is not None:
        data["method"] = method
    return {
        "status": "unavailable",
        "summary": summary,
        "data": data,
        "source": source,
    }
