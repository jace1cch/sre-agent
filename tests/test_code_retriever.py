"""Tests for code retrieval fallback behaviour."""

from pathlib import Path
from uuid import uuid4

from sre_agent.core.settings import AgentSettings
from sre_agent.rag import CodeRetriever
from sre_agent.rag.exact_search import extract_symbol


def _workspace_dir(name: str) -> Path:
    """Create a workspace-local test directory."""

    path = Path("tests/.tmp") / f"{name}-{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def test_code_retriever_searches_local_codebase() -> None:
    """Local text retrieval returns code matches from the configured path."""

    tmp_path = _workspace_dir("code-retriever")
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    (codebase / "WorkflowExecutor.java").write_text(
        "public class WorkflowExecutor {\n  // null pointer guard\n}\n",
        encoding="utf-8",
    )
    retriever = CodeRetriever(
        AgentSettings(
            _env_file=None,
            CODEBASE_PATH=str(codebase),
        )
    )

    result = retriever.search("null pointer")

    assert result["status"] == "completed"
    assert result["data"]["backend"] in {"exact_only", "hybrid"}
    assert result["data"]["method"] == "rrf"
    assert result["data"]["matches"][0]["file_path"].endswith("WorkflowExecutor.java")
    assert result["data"]["matches"][0]["start_line"] is not None


def test_extract_symbol_prefers_file_references() -> None:
    """File references beat generic exception names in exact retrieval."""

    assert extract_symbol("NullPointerException at WorkflowExecutor.java:234") == "WorkflowExecutor"


def test_extract_symbol_prefers_service_like_class_names() -> None:
    """Operational queries should prefer concrete class names over generic words."""

    assert extract_symbol("Redis get tool config failed RedisService") == "RedisService"


def test_code_retriever_falls_back_when_vector_store_is_missing() -> None:
    """Vector mode falls back to local text search when no vector store is wired."""

    tmp_path = _workspace_dir("code-retriever-vector")
    codebase = tmp_path / "codebase"
    codebase.mkdir()
    (codebase / "WorkflowExecutor.java").write_text(
        "public class WorkflowExecutor {\n  // token usage guard\n}\n",
        encoding="utf-8",
    )
    retriever = CodeRetriever(
        AgentSettings(
            _env_file=None,
            CODEBASE_PATH=str(codebase),
            CODEBASE_RETRIEVAL_MODE="vector",
            CODEBASE_VECTOR_STORE_PATH=str(tmp_path / "missing-index"),
        )
    )

    result = retriever.search("token usage")

    assert result["status"] == "completed"
    assert result["data"]["backend"] in {"exact_only", "hybrid"}
    assert result["data"]["matches"][0]["file_path"].endswith("WorkflowExecutor.java")
